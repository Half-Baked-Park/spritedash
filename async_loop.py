# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

# Adapted from Blender Cloud Addon (Sybren A. Stüvel, Francesco Siddi, Inês Almeida,
# Antony Riakiotakis) - http://github.com/dfelinto/blender-cloud-addon

"""Manages the asyncio loop"""

import asyncio
import concurrent.futures
import logging

import bpy
from bpy.app.handlers import persistent

log = logging.getLogger(__name__)

# The loop that the timer kicks. Kept here instead of calling asyncio.get_event_loop() on
# every kick, which is deprecated since python 3.12 and needlessly expensive besides.
_loop = None


def setup_asyncio_executor():
    """Sets up AsyncIO to run properly on each platform"""

    global _loop

    import sys

    if sys.platform == 'win32':
        asyncio.get_event_loop().close()
        # On Windows, the default event loop is SelectorEventLoop, which does
        # not support subprocesses. ProactorEventLoop should be used instead.
        # Source: https://docs.python.org/3/library/asyncio-subprocess.html
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    else:
        loop = asyncio.get_event_loop()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    loop.set_default_executor(executor)
    # loop.set_debug(True)

    _loop = loop


@persistent
def kick_async_loop():
    """Performs a single iteration of the asyncio event loop.

    :return: seconds until the next kick, or None to unregister the timer.
    """

    loop = _loop

    if loop is None or loop.is_closed():
        log.warning('loop closed, stopping the timer.')
        return None

    # NOTE do NOT walk asyncio.all_tasks() here. This runs many times a second, and all_tasks()
    # copies the internal weakset of tasks; when a connection drops or the machine wakes from
    # sleep, tasks die and get collected en masse, and the copy walks freed weakrefs. That is an
    # access violation inside python313.dll, i.e. blender goes down with no python traceback.
    loop.stop()
    loop.run_forever()

    return 0.001


def ensure_async_loop():
    if bpy.app.timers.is_registered(kick_async_loop):
        return

    log.debug('Starting asyncio loop')
    bpy.app.timers.register(kick_async_loop, persistent=True)


def erase_async_loop():
    log.debug('Erasing async loop')

    if bpy.app.timers.is_registered(kick_async_loop):
        bpy.app.timers.unregister(kick_async_loop)
