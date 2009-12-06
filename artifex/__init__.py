from subprocess import Popen, call, PIPE
import os, sys, re, cPickle, glob
VERSION = (0, 1, 1)

class Color:
    Clean = '\033[95m'
    Info = '\033[94m'
    Finished = '\033[92m'
    Warning = '\033[93m'
    Fail = '\033[91m'
    End = '\033[0m'

    @classmethod
    def disable(cls):
        cls.Clean = ''
        cls.Info = ''
        cls.Finished = ''
        cls.Warning = ''
        cls.Fail = ''
        cls.End = ''



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
    parser.add_option("-C", "--no-color",
                      action="store_false", dest="color", default=True,
                      help="disable color output")
    parser.add_option("--version",
                      action="store_true", dest="version", default=False,
                      help="output version information and exit")
    return parser.parse_args()

def _print_version():
    print u"""%s %s
Copyright (c) 2009 Kristoffer Gr\u00f6nlund.

License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.

Written by Kristoffer Gr\u00f6nlund.""" % ("artifex",
                                           ".".join(str(x) for x in VERSION))
    sys.exit(0)

_opts, _args = _parse_options()
if not _opts.color:
    Color.disable()

def info(s, *args, **kwargs):
    if not _opts.quiet:
        clr = Color.Info
        if 'color' in kwargs:
            clr = kwargs['color']
        print clr + (s % args) + Color.End

def debug(s, *args):
    if _opts.debug:
        print s % args

def _fileisnewer(mtime, fil):
    if os.path.isfile(fil):
        return os.stat(fil).st_mtime > mtime
    else:
        return False

def _flatten(lst):
    res = []
    for item in lst:
        if isinstance(item, (tuple, list)):
            res.extend(x for x in item)
        else:
            res.append(item)
    return res

def _listify(lst, globs=False):
    if isinstance(lst, basestring):
        lst = lst.split()
    if globs:
        return _flatten(glob.glob(l) for l in lst)
    else:
        return lst

class FileNotFoundException(Exception):
    pass

class Finder(object):
    def __init__(self):
        self.locations = ['.']

    def add(self, location):
        debug("Adding search location: %s", location)
        if location not in self.locations:
            self.locations.append(location)

    def locate(self, fil):
        path, name = os.path.split(fil)
        for loc in self.locations:
            if os.path.isfile(os.path.join(loc, fil)):
                return fil
        raise FileNotFoundException

class DepScanner(object):
    def __init__(self):
        self.include_re = None

    def _match_include(self, line):
        m = self.include_re.match(line)
        return m.group(1) if m else None

    def scan_include(self, finder, fil, collect=set([])):
        if not self.include_re:
            self.include_re = re.compile(r"\s*#\s*include\s*\"([^\"]+)\"")
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

class Dependencies(object):
    def __init__(self):
        self.scanner = DepScanner()
        self.finder = Finder()
        self._changed = False
        self._depends = {}

    def add(self, fil):
        ret = self.scanner.scan_include(self.finder, fil)
        self._depends[fil] = ret
        self._changed = True
        debug("?: %s -> %s", fil, ret)
        return ret

    def get(self, fil):
        return self._depends.get(fil, None)

    def save(self, to):
        if self._changed:
            debug("Saving dependencies: %s", self._depends)
            f = open(to, 'w')
            cPickle.dump(self._depends, f)
            f.close()

    def load(self, fname):
        if os.path.isfile(fname):
            f = open(fname)
            self._depends = cPickle.load(f)
            debug("Loaded dependencies: %s", self._depends)
            f.close()
            self._changed = False
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
        self.cflags = ["-g", "-Wall", "-Werror"]
        self.include = ['-I.']
        self.libs = []

        self._cachefile = os.path.join(self.tempdir, self.name+".cache")
        self._pkgconfig_proc = set([])
        self._cleaned = False
        self._target_path = None
        self._target_mtime = None

        self.load_cache()

    def save_cache(self):
        cachedata = {
            'cflags' : self.cflags,
            'include' : self.include,
            'libs' : self.libs,
            '_pkgconfig_proc' : self._pkgconfig_proc
            }
        f = open(self._cachefile, 'w')
        cPickle.dump(cachedata, f)
        f.close()

    def load_cache(self):
        if not _opts.rebuild and os.path.isfile(self._cachefile):
            f = open(self._cachefile)
            cachedata = cPickle.load(f)
            f.close()
            self.cflags = cachedata['cflags']
            self.libs = cachedata['libs']
            self.include = cachedata['include']
            self._pkgconfig_proc = cachedata['_pkgconfig_proc']

    def pkgconfig(self, names):
        for name in _listify(names):
            if name not in self._pkgconfig_proc:
                flags = Popen(["pkg-config", "--cflags", name], stdout=PIPE).communicate()[0].split()
                self.cflags = _listify(self.cflags) + flags
                libs = Popen(["pkg-config", "--libs", name], stdout=PIPE).communicate()[0].split()
                self.libs = _listify(self.libs) + libs
                debug("pkgconfig %s: %s, %s", name, flags, libs)
                self._pkgconfig_proc.add(name)

    def _objform(self, sourcefile):
        sppath = os.path.splitext(sourcefile)
        return os.path.join(self.tempdir, sppath[0]+".o")

    def _compile(self, fil):
        target = self._objform(fil)
        if not self.deps.is_dirty(fil, target):
            debug("+ %s -> %s - up to date, skipping", fil, target)
            return -1
        _mkdir(os.path.dirname(target))
        cmdline = [self.cc, "-c", "-o", target] + self.include + self.cflags + [fil]
        debug("%s", cmdline)
        pd = Popen(cmdline).pid
        info("+ %s", fil)
        return pd

    def _link(self, objs):
        relink = (self._target_mtime is None) or any(_fileisnewer(self._target_mtime, obj) for obj in objs)
        if relink:
            cmdline = [self.cc, "-o", self._target_path]  + self.include + self.cflags + self.libs + objs
            debug("%s", cmdline)
            call(cmdline)
            info("= %s", self.name, color=Color.Finished)
        else:
            debug("= %s - up to date, skipping", self.name)

    def _clean(self):
        if self._cleaned:
            return

        import shutil

        info("- %s %s", self.tempdir, self.outdir, color=Color.Clean)
        try:
            shutil.rmtree(self.tempdir)
        except OSError, e:
            pass

        try:
            shutil.rmtree(self.outdir)
        except OSError, e:
            pass

        self._cleaned = True

    def _build(self):
        self.include = _listify(self.include)
        self.source = _listify(self.source, globs=True)
        self.cflags = _listify(self.cflags)
        self.libs = _listify(self.libs)
        for inc in self.include:
            self.deps.finder.add(inc[2:])
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
        self.save_cache()

    def __call__(self):
        if _opts.version:
            _print_version()
        elif _opts.clean:
            self._clean()
        elif _opts.rebuild:
            self._clean()
            self._build()
        else:
            self._build()

_a_programs = []
_a_before = {}
_a_after = {}

def _artifex():
    for program in _a_programs:
        if program.name in _a_before:
            for fn in _a_before[program.name]:
                fn(program)
        program()
        if program.name in _a_after:
            for fn in _a_after[program.name]:
                fn(program)

import atexit
atexit.register(_artifex)

def program(buildfn):
    class Program(Target):
        def build(self):
            ok = [os.waitpid(p, 0) for p in (self._compile(dep) for dep in self.source) if p >= 0]
            self._link([self._objform(dep) for dep in self.source])
    target = buildfn.__name__
    bld = Program(buildfn.__name__)
    buildfn(bld)
    _a_programs.append(bld)
    return None

def before(fn):
    if fn.__name__ in _a_before:
        _a_before[fn.__name__].append(fn)
    else:
        _a_before[fn.__name__] = [fn]
    return None

def after(fn):
    if fn.__name__ in _a_after:
        _a_after[fn.__name__].append(fn)
    else:
        _a_after[fn.__name__] = [fn]
    return None
