#!/usr/bin/env python
from artifex import program

@program
def loverly(self):
    self.pkgconfig("glib-2.0")
    self.source = "main.c"
