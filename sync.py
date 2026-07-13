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

from __future__ import annotations
from aiohttp.web_ws import WebSocketResponse

import bpy
import asyncio
import aiohttp
import traceback
from aiohttp import web
from time import time

from . import async_loop
from . import util
from .messaging import encode
from .addon import addon


class Server():
    def __init__(self, host="", port=0):
        self.host = host
        self.port = port
        self._ws = None
        self._server = None
        self._site = None
        self._start_time = 0


    def send(self, msg, binary=True):
        if not self.connected:
            return

        if binary:
            asyncio.ensure_future(self._ws.send_bytes(msg, False))
        else:
            asyncio.ensure_future(self._ws.send_str(msg, False))


    @property
    def connected(self):
        return self._ws is not None and not self._ws.closed


    def start(self):
        started = False

        self._start_time = int(time())

        async def _start_a(self):
            nonlocal started
            self._server = web.Server(self._receive)

            runner = web.ServerRunner(self._server)
            await runner.setup()

            self._site = web.TCPSite(runner, self.host, self.port)
            await self._site.start()

            started = True

        async_loop.ensure_async_loop()
        stop = asyncio.wait_for(_start_a(self), timeout=5.0)

        try:
            asyncio.get_event_loop().run_until_complete(stop)
            util.refresh()
        except asyncio.TimeoutError:
            raise RuntimeError(f"Could not start server at {self.host}:{self.port}")


    def stop(self):
        async def _stop_a():
            if self._ws is not None:  # no connections happened
                await self._ws.close()
            await self._site.stop()
            await self._site._runner.cleanup()
            await self._server.shutdown()

        # the kick timer stops pumping the loop right after this, so the shutdown has to finish
        # here instead of being left as a floating task
        try:
            asyncio.get_event_loop().run_until_complete(asyncio.wait_for(_stop_a(), timeout=5.0))
        except Exception:
            # closing a socket that is already dead (aseprite gone, machine slept) throws, and
            # the server is going away either way
            traceback.print_exc()

        self._ws = None
        async_loop.erase_async_loop()
        util.refresh()


    async def _receive(self, request) -> WebSocketResponse:
        ws = web.WebSocketResponse(max_msg_size=0)
        self._ws = ws

        await ws.prepare(request)

        # client connected
        imgs = tuple(util.image_name(img) for img in bpy.data.images)
        await ws.send_bytes(encode.texture_list(imgs), False)
        bpy.ops.spritedash.report(message_type='INFO', message="Aseprite connected")
        util.refresh()

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await addon.handlers.process(msg.data)

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    bpy.ops.spritedash.report(message_type='ERROR', message=f"Connection closed with exception {ws.exception()}")

        except (OSError, aiohttp.ClientError):
            # the socket was torn down under us rather than closed politely, which is what a
            # sleeping machine or a killed aseprite looks like from here
            traceback.print_exc()

        finally:
            # client disconnected
            if self._ws is ws:
                self._ws = None
            bpy.ops.spritedash.report(message_type='INFO', message="Aseprite disconnected")
            util.refresh()

        return ws


class SB_OT_serv_start(bpy.types.Operator):
    bl_idname = "spritedash.start_server"
    bl_label = "Open Connection"
    bl_description = "Begin accepting connections from Aseprite"


    @classmethod
    def poll(self, ctx):
        return not addon.server_up


    def execute(self, context):
        addon.start_server()
        return {'FINISHED'}


class SB_OT_serv_stop(bpy.types.Operator):
    bl_idname = "spritedash.stop_server"
    bl_label = "Close Connection"
    bl_description = "Shut down Aseprite link"


    @classmethod
    def poll(self, ctx):
        return addon.server_up


    def execute(self, context):
        addon.stop_server()
        return {"FINISHED"}


class SB_OT_texture_list(bpy.types.Operator):
    bl_idname = "spritedash.texture_list"
    bl_label = "Update Texture List"
    bl_description = "Update Aseprite about which textures are used in the blendfile"


    @classmethod
    def poll(self, ctx):
        return addon.server_up


    def execute(self, context):
        images = (util.image_name(img) for img in bpy.data.images)
        msg = encode.texture_list(images)
        addon.server.send(msg)

        return {'FINISHED'}
