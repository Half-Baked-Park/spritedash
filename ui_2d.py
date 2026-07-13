# Copyright (c) 2021 lampysprites
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import bpy
import bmesh
import gpu
from mathutils import Matrix
from gpu_extras.batch import batch_for_shader
import numpy as np
from os import path

from .messaging import encode
from . import util
from .addon import addon


COLOR_MODES = [
    ('rgba', "RGBA", "32-bit color with transparency. If not sure, pick this one"),
    ('indexed', "Indexed", "Palettized image with arbitrary palette"),
    ('gray', "Grayscale", "Palettized with 256 levels of gray")]

UV_DEST = [
    ('texture', "Texture Source", "Show UV map in the file of the image editor's texture"),
    ('active', "Active Sprite", "Show UV map in the currently open documet")
]


class SB_OT_send_uv(bpy.types.Operator):
    bl_idname = "spritedash.set_uv"
    bl_label = "Send UV"
    bl_description = "Show UV in Aseprite"


    destination: bpy.props.EnumProperty(
        name="Show In",
        description="Which document's UV map will be created/updated in aseprite",
        items=UV_DEST,
        default='texture')


    size: bpy.props.IntVectorProperty(
        name="Resolution",
        description="The size for the created UVMap. The image is scaled to the size of the sprite",
        size=2,
        min=1,
        max=65535,
        default=(1, 1))

    color: bpy.props.FloatVectorProperty(
        name="UV color",
        description="Color to draw the UVs with",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0, 0.0),
        subtype='COLOR')

    weight: bpy.props.FloatProperty(
        name="UV Thickness",
        description="Thickness of the UV map lines at its original resolution",
        min=0,
        max=65535,
        default=0)


    @classmethod
    def poll(self, context):
        return addon.connected and (context.edit_object is not None or context.image_paint_object is not None)


    def target_image(self, context):
        """The texture to draw the UVs onto. The image editor's own image when run from there,
        otherwise one that's open in an image editor elsewhere in the screen, or the paint canvas"""
        space = context.space_data

        if space is not None and space.type == 'IMAGE_EDITOR' and space.image is not None:
            return space.image

        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR' and area.spaces.active.image is not None:
                return area.spaces.active.image

        return context.scene.tool_settings.image_paint.canvas


    def list_uv(self):
        ctx = bpy.context
        active = ctx.object
        lines = set()

        objects = [obj for obj in ctx.selected_objects if obj.type == 'MESH']
        if (active is not None) and (active not in objects) and (active.type == 'MESH'):
            objects.append(ctx.object)

        for obj in objects:

            try:
                bm = bmesh.from_edit_mesh(obj.data)
                bm_created = False # freeing an editmode bmesh crashes blender
            except: # if there's `elif`, why isn't there `exceptry`?
                try:
                    bm = bmesh.new()
                    bm_created = True
                    bm.from_mesh(obj.data)
                except:
                    self.report('WARNING', "UVMap drawing skipped: can't access mesh data")
                    continue

            uv = bm.loops.layers.uv.active

            # get all edges
            for face in bm.faces:
                if not face.select:
                    continue

                for i in range(0, len(face.loops)):
                    a = face.loops[i - 1][uv].uv.to_tuple()
                    b = face.loops[i][uv].uv.to_tuple()

                    # sorting prevents the edge from being added twice for differently directed loops
                    # order doesn't really matter, just that there is one
                    if a > b:
                        a, b = b, a

                    lines.add((a, b))

            if bm_created:
                bm.free()

        return lines


    def uvmap_size(self, context):
        scale = addon.prefs.uv_scale
        # 대상을 못 찾는 3d 뷰 쪽에서도 기본 스프라이트 크기 × scale 이 나오게 (256 × 8 = 2048)
        size = [256, 256]

        img = self.target_image(context)
        if img is not None:
            size = img.size

        return [int(size[0] * scale), int(size[1] * scale)]


    def execute(self, context):
        w, h = self.size
        source = ""

        if self.destination == 'texture':
            img = self.target_image(context)
            if img is None:
                self.report({"ERROR"}, "'Texture Source' needs a texture open in an Image Editor, or set as the texture paint canvas")
                return {'CANCELLED'}
            source = util.image_name(img)

        aa = addon.prefs.uv_aa
        weight = self.weight
        lines = self.color[0:3] + (1.0,)

        offscreen = gpu.types.GPUOffScreen(w, h)

        coords = [c for pt in self.list_uv() for c in pt]
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": coords})

        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))

            with gpu.matrix.push_pop():
                # see explanation in https://blender.stackexchange.com/questions/153697/gpu-python-module-why-drawed-pixels-are-shifted-in-the-result-image
                projection_matrix = Matrix.Diagonal((2.0, -2.0, 1.0))
                projection_matrix = Matrix.Translation((-1.0, 1.0, 0.0)) @ projection_matrix.to_4x4()
                gpu.matrix.load_projection_matrix(projection_matrix)

                gpu.state.line_width_set(weight)
                # GL_LINE_SMOOTH은 gpu 모듈에 대응 API가 없어 드롭. 블렌딩만 유지
                if aa:
                    gpu.state.blend_set('ALPHA')
                else:
                    gpu.state.blend_set('NONE')

                shader.bind()
                shader.uniform_float("color", lines)
                batch.draw(shader)

            # retrieve the texture — 오프스크린 프레임버퍼에서 RGBA 픽셀 리드백 (공식 gpu.offscreen 예제 패턴)
            buffer = fb.read_color(0, 0, w, h, 4, 0, 'UBYTE')
            buffer.dimensions = w * h * 4
            nbuf = np.array(buffer, dtype=np.uint8)

        # send data
        msg = encode.uv_map(
                size=(w, h),
                sprite=source,
                pixels=nbuf.tobytes(),
                layer=addon.prefs.uv_layer,
                opacity=int(addon.prefs.uv_color[3] * 255))
        if source:
            msg = encode.batch((encode.sprite_focus(source), msg))

        addon.server.send(msg)

        return {"FINISHED"}


    def invoke(self, context, event):
        if tuple(self.size) == (1, 1):
            self.size = self.uvmap_size(context)

        if tuple(self.color) == (0.0, 0.0, 0.0, 0.0):
            self.color = addon.prefs.uv_color

        if self.weight == 0.0:
            self.weight = addon.prefs.uv_weight

        return context.window_manager.invoke_props_dialog(self)



class SB_OT_open_sprite(bpy.types.Operator):
    bl_idname = "spritedash.open_sprite"
    bl_label = "Open..."
    bl_description = "Set up a texture from a file using Aseprite"
    bl_options = {'REGISTER', 'UNDO'}


    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    # dialog settings
    filter_glob: bpy.props.StringProperty(default="*.ase;*.aseprite;.bmp;.flc;.fli;.gif;.ico;.jpeg;.jpg;.pcx;.pcc;.png;.tga;.webp", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})


    @classmethod
    def poll(self, context):
        return addon.connected


    def execute(self, context):
        source = bpy.path.abspath(self.filepath)
        _, name = path.split(source)
        img = None

        for i in bpy.data.images:
            # we might have this image opened already
            if i.sb_source == source:
                img = i
                break
        else:
            # create a stub that will be filled after receiving data
            img = util.new_packed_image(name, 1, 1)
            img.sb_source = source

        # switch to the image in the editor
        if context.area.type == 'IMAGE_EDITOR':
            context.area.spaces.active.image = img

        msg = encode.sprite_open(source)
        addon.server.send(msg)

        return {'FINISHED'}


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SB_OT_new_sprite(bpy.types.Operator):
    bl_idname = "spritedash.new_sprite"
    bl_label = "New"
    bl_description = "Set up a new texture using Aseprite"
    bl_options={'REGISTER', 'UNDO'}

    sprite: bpy.props.StringProperty(
        name="Name",
        description="Name of the texture. It will also be displayed on the tab in Aseprite until you save the file",
        default="Sprite")

    size: bpy.props.IntVectorProperty(
        name="Size",
        description="Size of the created canvas",
        default=(128, 128),
        size=2,
        min=1,
        max=65535)

    mode: bpy.props.EnumProperty(
        name="Color Mode",
        description="Color mode of the created sprite",
        items=COLOR_MODES,
        default='rgba')


    @classmethod
    def poll(self, context):
        return addon.connected


    def execute(self, context):
        if not self.sprite:
            self.report({'ERROR'}, "The sprite must have a name")
            return {'CANCELLED'}

        # create a stub that will be filled after receiving data
        img = util.new_packed_image(self.sprite, 1, 1)
        img.sb_source = img.name # can get an additional suffix, e.g. "Sprite.001"
        # switch to it in the editor
        if context.area.type == 'IMAGE_EDITOR':
            context.area.spaces.active.image = img

        mode = 0
        for i,m in enumerate(COLOR_MODES):
            if m[0] == self.mode:
                mode = i

        msg = encode.sprite_new(
            name=img.sb_source,
            size=self.size,
            mode=mode)

        addon.server.send(msg)

        return {'FINISHED'}


    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class SB_OT_edit_sprite(bpy.types.Operator):
    bl_idname = "spritedash.edit_sprite"
    bl_label = "Edit"
    bl_description = "Open the file for this texture with Aseprite"


    @classmethod
    def poll(self, context):
        return addon.connected and context.area.type == 'IMAGE_EDITOR' \
            and context.edit_image and context.edit_image.has_data


    def execute(self, context):
        img = context.edit_image
        edit_name = util.image_name(img)
        msg = None

        if path.exists(edit_name):
            msg = encode.sprite_open(name=edit_name)
        else:
            pixels = np.asarray(np.array(img.pixels) * 255, dtype=np.ubyte)
            pixels.shape = (img.size[1], pixels.size // img.size[1])
            pixels = np.ravel(pixels[::-1,:])

            msg = encode.image(
                name=img.name,
                size=img.size,
                pixels=pixels.tobytes())

        addon.server.send(msg)

        return {'FINISHED'}


class SB_OT_edit_sprite_copy(bpy.types.Operator):
    bl_idname = "spritedash.edit_sprite_copy"
    bl_label = "Edit Copy"
    bl_description = "Open copy of the image in a new file in Aseprite, without syncing"


    @classmethod
    def poll(self, context):
        return addon.connected and context.area.type == 'IMAGE_EDITOR' \
            and context.edit_image and context.edit_image.has_data


    def execute(self, context):
        img = context.edit_image

        pixels = np.asarray(np.array(img.pixels) * 255, dtype=np.ubyte)
        pixels.shape = (img.size[1], pixels.size // img.size[1])
        pixels = np.ravel(pixels[::-1,:])

        msg = encode.image(
            name="",
            size=img.size,
            pixels=pixels.tobytes())

        addon.server.send(msg)

        return {'FINISHED'}


class SB_OT_replace_sprite(bpy.types.Operator):
    bl_description = "Replace current texture with a file using Aseprite"
    bl_idname = "spritedash.replace_sprite"
    bl_label = "Replace..."
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    # dialog settings
    filter_glob: bpy.props.StringProperty(default="*.ase;*.aseprite;.bmp;.flc;.fli;.gif;.ico;.jpeg;.jpg;.pcx;.pcc;.png;.tga;.webp", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return addon.connected and context.area.type == 'IMAGE_EDITOR'

    def execute(self, context):
        source = bpy.path.abspath(self.filepath)
        context.edit_image.sb_source = source
        msg = encode.sprite_open(source)
        addon.server.send(msg)

        return {'FINISHED'}


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
