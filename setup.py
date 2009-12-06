#!/usr/bin/env python
from setuptools import setup
import re

def find_version():
    for line in open("artifex/__init__.py").readlines():
        if line.startswith("VERSION = "):
            return ".".join(re.findall(r'(\d+)', line))
    return '0.1.0'

setup(
    name='artifex',
    version=find_version(),
    description='a builder for c/c++',
    author='Kristoffer Gronlund',
    author_email='kristoffer.gronlund@purplescout.se',
    url='github.com/krig',
    packages=['artifex'],
    license='GPL',
    install_requires=['setuptools'],
    data_files=[('share/artifex/examples', ['examples/loverly.mk',
                                            'examples/corvus.mk'])])
