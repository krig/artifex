#!/usr/bin/env python
from artifex import *

@config_h
def breakout(cfg):
    cfg.name = "config.hpp"
    cfg.DEBUG = 1

@program
def breakout(s):
    s.pkgconfig(["freetype2", "gl"])
    s.pkgconfig(tool="sdl-config")
    s.include += ["-Iinclude"]
    s.libs += ["-lGLU", "-lfreeimage"]
    s.source = ["src/*.cpp", "test/breakout.cpp"]
