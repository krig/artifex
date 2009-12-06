# artifex

A make replacement for small C/C++ projects.

## Why?

It is my opinion that the GNU ecosystem has a serious build
problem. The autotools suite is old and obscure, written in M4 which
no one uses for anything else as far as I know (and with good reason,
as far as I can tell). It is slow and cumbersome, and honestly doesn't
really get you very far beyond a plain Makefile.

There are other make replacements, and they all have their strengths
and drawbacks. One universal truth, however, is that they are all
lacking in some way. CMake and Jam both continue the autotools
tradition of being written in bizarre languages, Scons is unbearably
slow, and waf is.. well, Waf is pretty good, I'd recommend it for
larger projects.

I, on the other hand, wanted something that does the right thing for
me by default. Basically, I am trying to make as many assumptions as
possible in the build tool about how the project is structured, unless
you say otherwise. In some cases, it might not even be possible to
override some assumption of the build tool. Either you can modify it
yourself, or you can use something else. I won't blame you. I still
use waf where it makes sense.

## Build script

A basic build script looks like this:

    #!/usr/bin/env python
    from artifex import *
    @program
    def myprogram(self):
        self.source = ["main.c", "util.c"]

Place it in your project root, place the artifex directory somewhere
where python can access it, and execute the script.

This will dependency-scan and compile main.c and util.c into a binary,
placed in the `bin/` folder, called `myprogram`.

Artifex detects dependencies and only rebuilds objects if needed. If
this is not desired, run the build script with `-r` as a parameter.

To remove all built targets and intermediary files, run the script
with `-c` as a parameter.

The dependency scanner will try to skip recompiling files as much as
possible, storing SHA-1 checksums for all touched files (like git, how
*elite*!) and only recompiling if the files truly have changed.

There may be bugs, but if something doesn't rebuild when it should,
just pass `-r` to the command line and there you go.

Some tools don't like it when you use globs (like `*.c`) in the build
script and then remove a file. Artifex is no different here, and may
not rebuild your executable when this happens (it shouldn't make
broken rebuilds, though). Again, `-r` is your friend.

## TODO

* Better support for multiple source and include directories.
  Actually, this should work pretty well. See the corvus.mk example
  script where I include files from a separate directory, and source
  files from two different directories.

