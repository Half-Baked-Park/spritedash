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
from .addon import addon
import numpy as np
from math import pi


def scale_image(image, scale):
    """Scale image in-place without filtering"""
    w, h = image.size
    px = np.array(image.pixels, dtype=np.float32)
    px.shape = (w, h, 4)
    image.scale(w * scale, h * scale)
    px = px.repeat(scale, 0).repeat(scale, 1)
    try:
        # version >= 2.83
        image.pixels.foreach_set(px.ravel())
    except:
        # version < 2.83
        image.pixels[:] = px.ravel()
    image.update()


class SB_OT_reference_add(bpy.types.Operator):
    bl_idname = "spritedash.reference_add"
    bl_label = "Add Reference"
    bl_description = "Add reference image with pixels aligned to the view grid"
    bl_options = {'REGISTER', 'UNDO'}

    scale: bpy.props.IntProperty(
        name="Prescale",
        description="Prescale the image",
        default=10,
        min=1,
        max=50)

    opacity: bpy.props.FloatProperty(
        name="Opacity",
        description="Image's viewport opacity",
        default=0.33,
        min=0.0,
        max=1.0,
        subtype='FACTOR')

    selectable: bpy.props.BoolProperty(
        name="Selectable",
        description="If checked, the image can be selected in the viewport, otherwise only in the outliner",
        default=True)

    # dialog
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.bmp;*.png", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})


    @classmethod
    def poll(self, context):
        return not context.object or context.object.mode == 'OBJECT'


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


    def execute(self, context):
        image = bpy.data.images.load(self.filepath)
        #image.pack() # NOTE without packing it breaks after reload but so what
        w, h = image.size
        scale_image(image, self.scale)
        image.sb_scale = self.scale

        bpy.ops.object.add(align='WORLD', rotation=(pi/2, 0, 0), location = (0, 0, 0))
        ref = context.active_object
        ref.data = image
        ref.empty_display_type = 'IMAGE'
        ref.use_empty_image_alpha = self.opacity < 1.0
        ref.color[3] = self.opacity
        ref.empty_display_size = max(w, h) * context.space_data.overlay.grid_scale
        if not self.selectable:
            ref.hide_select = True
            self.report({'INFO'}, "The reference won't be selectable. Use the outliner to reload/delete it")

        return {'FINISHED'}


class SB_OT_reference_reload(bpy.types.Operator):
    bl_idname = "spritedash.reference_reload"
    bl_label = "Reload Reference"
    bl_description = "Reload reference while keeping it prescaled"
    bl_options = {'REGISTER', 'UNDO'}


    @classmethod
    def poll(self, context):
        return context.object and context.object.type == 'EMPTY' \
                and context.object.empty_display_type == 'IMAGE'


    def execute(self, context):
        image = context.object.data
        image.reload()
        scale_image(image, image.sb_scale)

        return {'FINISHED'}


class SB_OT_reference_reload_all(bpy.types.Operator):
    bl_idname = "spritedash.reference_reload_all"
    bl_label = "Reload All References"
    bl_description = "Reload all references (including non-spritedash's), while keeping them prescaled"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in bpy.data.objects:
            if obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE':
                image = obj.data
                image.reload()
                scale_image(image, image.sb_scale)

        return {'FINISHED'}



class _SB_PT_spritedash:
    ## 공통 믹스인 — Connection 섹션을 3D/Image 두 패널이 공유. `_` 접두사라 register 안 됨
    bl_category = "Spritedash"
    bl_region_type = "UI"

    def draw_connection(self, context):
        layout = self.layout

        row = layout.row()
        status = "Off"
        icon = 'UNLINKED'
        if addon.connected:
            status = "Connected"
            icon = 'CHECKMARK'
        elif addon.server_up:
            status = "Waiting..."
            icon = 'SORTTIME'

        row.label(text=status, icon=icon)

        row = row.row()
        row.alignment = 'RIGHT'
        if addon.server_up:
            row.operator("spritedash.stop_server", text="Stop", icon="DECORATE_LIBRARY_OVERRIDE")
        else:
            row.operator("spritedash.start_server", text="Connect", icon="DECORATE_LINKED")
        row.operator("spritedash.preferences", icon='PREFERENCES', text="", emboss=False)


class SB_PT_spritedash_3d(_SB_PT_spritedash, bpy.types.Panel):
    ## 3D 뷰포트 사이드바 — Connection + Reference(뷰포트 전용)
    bl_idname = "SB_PT_spritedash_3d"
    bl_label = "Spritedash"
    bl_space_type = "VIEW_3D"

    def draw(self, context):
        self.draw_connection(context)

        layout = self.layout
        layout.separator()
        col = layout.column(align=True)
        col.label(text="Sprite:")
        # 3D 뷰에는 image editor 컨텍스트가 없으니 aseprite가 열어둔 문서에 그리는 쪽이 기본
        col.operator("spritedash.set_uv", icon='UV_VERTEXSEL').destination = 'active'

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Reference:")
        col.operator("spritedash.reference_add")
        col.operator("spritedash.reference_reload")
        col.operator("spritedash.reference_reload_all")


class SB_PT_spritedash_image(_SB_PT_spritedash, bpy.types.Panel):
    ## Image/UV Editor 사이드바 — Connection + Sprite(텍스처/UV 조작)
    bl_idname = "SB_PT_spritedash_image"
    bl_label = "Spritedash"
    bl_space_type = "IMAGE_EDITOR"

    def draw(self, context):
        self.draw_connection(context)

        layout = self.layout
        layout.separator()
        col = layout.column(align=True)
        col.label(text="Sprite:")
        col.operator("spritedash.new_sprite", icon='FILE_NEW')
        col.operator("spritedash.open_sprite", icon='FILE_FOLDER')
        col.operator("spritedash.edit_sprite", icon='GREASEPENCIL')
        col.operator("spritedash.edit_sprite_copy")
        col.operator("spritedash.replace_sprite")
        col.separator()
        col.operator("spritedash.set_uv", icon='UV_VERTEXSEL')
