#!/usr/bin/env python
from artifex import *

@program
def loverly(s):
    s.pkgconfig("glib-2.0")
    s.source = "src/*.c"
