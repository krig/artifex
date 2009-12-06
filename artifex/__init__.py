from subprocess import Popen, call, PIPE
import os, sys, re, cPickle
VERSION = (0, 1, 1)

def _mkdir(dr):
    if os.path.isfile(dr):
        raise OSError("Can't create directory %s - a file by the same name already exists" % (dr))
    elif not os.path.isdir(dr):
        parent,name = os.path.split(dr)
        if parent and not os.path.isdir(parent):
            _mkdir(parent)
        if name:
            os.mkdir(dr)

def _cppname(nm):
    ext = os.path.splitext(nm)[1]
    return ext in ('.cc', '.C', '.cxx', '.cpp', '.c++')

def _parse_options():
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-c", "--clean",
                      action="store_true", dest="clean", default=False,
                      help="Remove any intermediates instead of compiling")
    parser.add_option("-r", "--rebuild",
                      action="store_true", dest="rebuild", default=False,
                      help="Rebuild all targets")
    parser.add_option("-q", "--quiet",
                      action="store_true", dest="quiet", default=False,
                      help="don't print status messages to stdout")
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="debug", default=False,
                      help="print debug messages to stdout")
    parser.add_option("--version",
                      action="store_true", dest="version", default=False,
                      help="output version information and exit")
    return parser.parse_args()

_opts, _args = _parse_options()

def info(s, *args):
    if not _opts.quiet:
        print s % args

def debug(s, *args):
    if _opts.debug:
        print s % args

class FileNotFoundException(Exception):
    pass

class Finder(object):
    def __init__(self):
        pass

    def locate(self, fil):
        if os.path.isfile(fil):
            return fil
        raise FileNotFoundException

class DepScanner(object):
    def __init__(self):
        self.include_re = re.compile(r"\s*#\s*include\s*\"([^\"]+)\"")

    def _match_include(self, line):
        m = self.include_re.match(line)
        return m.group(1) if m else None

    def scan_include(self, finder, fil, collect=set([])):
        try:
            for line in open(finder.locate(fil)).readlines():
                m = self._match_include(line)
                if m:
                    self.scan_include(finder, m, collect)
            collect.add(fil)
        except IOError, e:
            pass
        except FileNotFoundException, e:
            pass
        return collect

def _fileisnewer(mtime, fil):
    if os.path.isfile(fil):
        return os.stat(fil).st_mtime > mtime
    else:
        return False

class Dependencies(object):
    def __init__(self):
        self.scanner = DepScanner()
        self.finder = Finder()
        self._depends = {}

    def add(self, fil):
        ret = self.scanner.scan_include(self.finder, fil)
        self._depends[fil] = ret
        debug("?: %s -> %s", fil, ret)
        return ret

    def get(self, fil):
        return self._depends.get(fil, None)

    def save(self, to):
        debug("%s << %s", to, self._depends)
        f = open(to, 'w')
        cPickle.dump(self._depends, f)
        f.close()

    def load(self, fname):
        if os.path.isfile(fname):
            f = open(fname)
            self._depends = cPickle.load(f)
            debug("%s >> %s", fname, self._depends)
            f.close()
        else:
            self._depends = {}

    def is_dirty(self, iname, oname):
        deps = self.get(iname)
        if not deps:
            deps = self.add(iname)

        if not os.path.isfile(oname):
            del self._depends[iname]
            return True
        omtime = os.stat(oname).st_mtime

        for dep in deps:
            if _fileisnewer(omtime, dep):
                del self._depends[iname]
                return True
        return False

class Target(object):
    def __init__(self, name):
        self.deps = Dependencies()
        self.outdir = "bin/"
        self.tempdir = "obj/"
        self.name = name
        self.debug = False
        self.source = []
        self.cc = "gcc"
        self.cflags = ["-g"]
        self.libs = []

        self._cleaned = False
        self._target_path = None
        self._target_mtime = None

    def pkgconfig(self, name):
        flags = Popen(["pkg-config", "--cflags", name], stdout=PIPE).communicate()[0].split()
        self.cflags = self.cflags + flags
        libs = Popen(["pkg-config", "--libs", name], stdout=PIPE).communicate()[0].split()
        self.libs = self.libs + libs
        debug("pkgconfig %s: %s, %s", name, flags, libs)

    def _objform(self, sourcefile):
        sppath = os.path.splitext(sourcefile)
        return os.path.join(self.tempdir, sppath[0]+".o")

    def _compile(self, fil):
        target = self._objform(fil)
        if not self.deps.is_dirty(fil, target):
            debug("+ %s -> %s - not dirty, skipping", fil, target)
            return -1
        info("+ %s", fil)
        cmdline = [self.cc] + ["-c", "-o", target] + self.cflags + [fil]
        debug("%s", " ".join(cmdline))
        return Popen(cmdline).pid

    def _link(self, objs):
        relink = (self._target_mtime is None) or any(_fileisnewer(self._target_mtime, obj) for obj in objs)
        if relink:
            info("= %s", self.name)
            cmdline = [self.cc] + self.cflags + ["-o", self._target_path] + self.libs + objs
            debug("%s", " ".join(cmdline))
            call(cmdline)
        else:
            debug("%s up to date, skipping", self.name)

    def _clean(self):
        if self._cleaned:
            return

        import shutil

        try:
            info("- %s", self.tempdir)
            shutil.rmtree(self.tempdir)
        except OSError, e:
            pass

        try:
            info("- %s", self.outdir)
            shutil.rmtree(self.outdir)
        except OSError, e:
            pass

        self._cleaned = True

    def _build(self):
            if isinstance(self.source, basestring):
                self.source = self.source.split()
            if self.cc == "gcc" and any(_cppname(s) for s in self.source):
                self.cc = "g++"
            self._target_path = os.path.join(self.outdir, self.name)
            try:
                self._target_mtime = os.stat(self._target_path).st_mtime
            except OSError, e:
                self._target_mtime = None
            # force clean if build script changed
            if self._target_mtime:
                me = sys.argv[0]
                if _fileisnewer(self._target_mtime, me):
                    self._clean()
            _mkdir(self.outdir)
            _mkdir(self.tempdir)
            depfile = os.path.join(self.tempdir, self.name + ".depends")
            self.deps.load(depfile)
            self.build()
            self.deps.save(depfile)

    def __call__(self):
        if _opts.version:
            print "%s %s" % ("artifex", ".".join(str(x) for x in VERSION))
            print u"""Copyright (c) 2009 Kristoffer Gr\u00f6nlund.

License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.

Written by Kristoffer Gr\u00f6nlund."""
            sys.exit(0)
        elif _opts.clean:
            self._clean()
        elif _opts.rebuild:
            self._clean()
            self._build()
        else:
            self._build()

import atexit

def program(buildfn):
    class Program(Target):
        def build(self):
            pids = [self._compile(dep) for dep in self.source]
            ok = [os.waitpid(p, 0) for p in pids if p >= 0]
            self._link([self._objform(dep) for dep in self.source])
    target = buildfn.__name__
    bld = Program(buildfn.__name__)
    buildfn(bld)

    atexit.register(bld)
    return bld
