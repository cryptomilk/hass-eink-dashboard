# Copyright 2026 Kit Lerman
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Exceptions shared by the e-ink dashboard renderer."""

from __future__ import annotations


class RenderNotReady(Exception):
    """A widget's data has not loaded yet; keep the last good image.

    Raise this only for transient conditions, such as an entity that is
    absent from the states snapshot while Home Assistant is still
    starting.  Genuine faults should raise anything else, so that they
    are still logged in full with a traceback.
    """
