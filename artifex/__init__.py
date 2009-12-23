from subprocess import Popen, call, PIPE
import os, sys, re, cPickle, glob, hashlib, pprint
VERSION = (0, 1, 2)

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

def _calc_checksum_file(fil):
    try:
        f = open(fil)
        return hashlib.sha1(f.read()).hexdigest()
    finally:
        f.close()

def _calc_checksum_str(string):
    return hashlib.sha1(string).hexdigest()

def _fileisnewer(mtime, fil):
    if os.path.isfile(fil):
        return os.stat(fil).st_mtime > mtime
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
        self.locations = ['']
        self.locstack = []

    def add(self, location):
        if location not in self.locations:
            self.locations.append(location)

    def push(self, location):
        self.locstack = [location] + self.locstack

    def pop(self):
        self.locstack = self.locstack[1:]

    def locate(self, fil):
        path, name = os.path.split(fil)
        for loc in self.locstack:
            if os.path.isfile(os.path.join(loc, fil)):
                return os.path.join(loc, fil)
        for loc in self.locations:
            if os.path.isfile(os.path.join(loc, fil)):
                return os.path.join(loc, fil)
        debug("%s: not found, ignoring", fil)
        raise FileNotFoundException

class DepScanner(object):
    def __init__(self):
        self.include_re = None

    def _match_include(self, line):
        m = self.include_re.match(line)
        return m.group(1) if m else None

    def scan_include(self, finder, fil, dependencies, collect=set([])):
        if not self.include_re:
            self.include_re = re.compile(r"\s*#\s*include\s*\"([^\"]+)\"")
        try:
            finder.push(os.path.dirname(fil))
            found = finder.locate(fil)
            if dependencies.in_cache(found):
                debug("%s: in cache", found)
                return collect
            handle = open(found)
            lines = handle.readlines()
            handle.close()
            for line in lines:
                m = self._match_include(line)
                if m:
                    self.scan_include(finder, m, dependencies, collect)
            finder.pop()
            mtime = os.stat(found).st_mtime
            cs = _calc_checksum_str(''.join(lines))
            dependencies.add_to_cache(found, mtime, cs)
            debug("adding %s", found)
            collect.add(found)
        except IOError, e:
            debug("DepScanner: %s", e)
        except FileNotFoundException, e:
            pass
        return collect

class Dependencies(object):
    def __init__(self):
        self.scanner = DepScanner()
        self.finder = Finder()
        self.changed = False
        self.depends = {} # filename -> [filename]
        self.filecache = {} # filename -> (mtime, sha-1)
        self.objcache = {} # objname -> (mtime, sha-1)

    def add_to_cache(self, fil, mtime, checksum):
        debug("Adding to file cache: %s -> (%s, %s)", fil, mtime, checksum)
        self.changed = True
        self.filecache[fil] = (mtime, checksum)

    def in_cache(self, fil):
        return fil in self.filecache

    def add(self, fil):
        ret = self.scanner.scan_include(self.finder, fil, self, set([fil]))
        self.depends[fil] = ret
        self.changed = True
        debug("?: %s -> %s", fil, ret)
        return ret

    def _get(self, fil):
        return self.depends.get(fil, None)

    def save(self, to):
        if self.changed:
            f = open(to, 'w')
            cPickle.dump(self.depends, f, cPickle.HIGHEST_PROTOCOL)
            cPickle.dump(self.filecache, f, cPickle.HIGHEST_PROTOCOL)
            cPickle.dump(self.objcache, f, cPickle.HIGHEST_PROTOCOL)
            f.close()
            debug("Saved dependencies to %s", to)

    def load(self, fname):
        if os.path.isfile(fname):
            f = open(fname)
            self.depends = cPickle.load(f)
            self.filecache = cPickle.load(f)
            self.objcache = cPickle.load(f)
            debug("Loaded dependencies:\n%s", pprint.pformat(self.depends, indent=2, width=60))
            debug("Loaded filecache:\n%s", pprint.pformat(self.filecache, indent=2, width=60))
            debug("Loaded objcache:\n%s", pprint.pformat(self.objcache, indent=2, width=60))
            f.close()
            self.changed = False

            debug("Checking for changes to file cache...")
            self._refresh_filecache()
            debug("Done.")
        else:
            self.depends = {}

    def _refresh_filecache(self):
        """recheck checksums, drop files that have changed"""
        rm = []
        for fil, (mtime, sha1) in self.filecache.iteritems():
            if not os.path.isfile(fil):
                debug("not a file: %s", fil)
                rm.append(fil)
                continue
            nmtime = os.stat(fil).st_mtime
            debug("%s: mtime: %s, nmtime: %s", fil, mtime, nmtime)
            if nmtime > mtime:
                nsha1 = _calc_checksum_file(fil)
                if nsha1 != sha1:
                    rm.append(fil)
        for fil in rm:
            debug("%s changed, dropping from file cache", fil)
            del self.filecache[fil]

    def add_to_objcache(self, oname):
        omtime = os.stat(oname).st_mtime
        osha1 = _calc_checksum_file(oname)
        debug("Adding %s -> (%s, %s) to objcache", oname, omtime, osha1)
        self.changed = True
        self.objcache[oname] = (omtime, osha1)
        return (omtime, osha1)

    def is_dirty(self, iname, oname):
        deps = self._get(iname)
        if not deps:
            deps = self.add(iname)

        if not os.path.isfile(oname):
            debug("not file: %s", oname)
            return True

        omtime, osha1 = self.objcache.get(oname, (None, None))
        if not omtime:
            omtime, osha1 = self.add_to_objcache(oname)

        for dep in deps:
            if dep not in self.filecache:
                debug("%s changed, %s is dirty", dep, oname)
                self.changed = True
                del self.depends[iname]
                del self.objcache[oname]
                return True
            else:
                mtime, sha1 = self.filecache[dep]
                if mtime > omtime:
                    debug("%s is newer than %s", dep, oname)
                    self.changed = True
                    del self.depends[iname]
                    del self.objcache[oname]
                    return True
                else:
                    debug("%s:%s not changed", dep, oname)
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
        self.pkg_cflags = []
        self.pkg_libs = []

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
            'pkg_cflags' : self.pkg_cflags,
            'pkg_libs' : self.pkg_libs,
            '_pkgconfig_proc' : self._pkgconfig_proc
            }
        f = open(self._cachefile, 'w')
        cPickle.dump(cachedata, f, cPickle.HIGHEST_PROTOCOL)
        f.close()

    def load_cache(self):
        if not _opts.rebuild and os.path.isfile(self._cachefile):
            f = open(self._cachefile)
            cachedata = cPickle.load(f)
            f.close()
            self.cflags = cachedata['cflags']
            self.pkg_cflags = cachedata['pkg_cflags']
            self.pkg_libs = cachedata['pkg_libs']
            self.libs = cachedata['libs']
            self.include = cachedata['include']
            self._pkgconfig_proc = cachedata['_pkgconfig_proc']

    def pkgconfig(self, names = [], tool="pkg-config"):
        names = _listify(names)
        if names == []:
            names = ['']
        for name in names:
            pkgid = tool+":"+name
            if pkgid not in self._pkgconfig_proc:
                flags = Popen([tool, "--cflags"] + ([name] if name else []), stdout=PIPE).communicate()[0].split()
                self.pkg_cflags = _listify(self.pkg_cflags) + flags
                libs = Popen([tool, "--libs"] + ([name] if name else []), stdout=PIPE).communicate()[0].split()
                self.pkg_libs = _listify(self.pkg_libs) + libs
                debug("%s: %s, %s", pkgid, flags, libs)
                self._pkgconfig_proc.add(pkgid)

    def _objform(self, sourcefile):
        sppath = os.path.splitext(sourcefile)
        return os.path.join(self.tempdir, sppath[0]+".o")

    def _compile(self, fil):
        target = self._objform(fil)
        if not self.deps.is_dirty(fil, target):
            debug("+ %s -> %s - up to date, skipping", fil, target)
            return -1
        _mkdir(os.path.dirname(target))
        cmdline = [self.cc, "-c", "-o", target] + self.include + self.cflags + self.pkg_cflags + [fil]
        debug("%s", cmdline)
        pd = Popen(cmdline, shell=False).pid
        info("+ %s", fil)
        return pd

    def _link(self, objs):
        relink = (self._target_mtime is None) or any(_fileisnewer(self._target_mtime, obj) for obj in objs)
        if relink:
            cmdline = [self.cc, "-o", self._target_path]  + self.include + self.cflags + self.pkg_cflags + self.libs + self.pkg_libs + objs
            debug("%s", cmdline)
            ret = call(cmdline)
            info("= %s", self.name, color=Color.Finished)
            return ret == 0
        else:
            debug("= %s - up to date, skipping", self.name)
            return True

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
        self.pkg_cflags = _listify(self.pkg_cflags)
        self.pkg_libs = _listify(self.pkg_libs)
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
        if self.build():
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
            ok = [(dep, ret[1] == 0) for dep, ret in zip(self.source, ok)]
            for dep, result in ok:
                debug("Compile: %s - %s", dep, result)

            if any(not ret for _, ret in ok):
                debug("Build failed.")
                return False
            else:
                return self._link([self._objform(dep) for dep in self.source])
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

def config_h(fn):
    file_template = """#ifndef CONFIG_H_ARTIFEX
#define CONFIG_H_ARTIFEX

%(values)s

#endif/*CONFIG_H_ARTIFEX*/
"""
    value_template = """#define %s %s
"""
    class ConfigH(object):
        def __init__(self, pkg):
            self.pkg = pkg
            self.name = "config.h"
        def write(self):
            values = [(x, getattr(cfg, x)) for x in dir(cfg) if not (x.startswith('_') or x in ['pkg', 'name', 'write'])]
            valuestr = ""
            for key, val in values:
                if isinstance(val, basestring):
                    valuestr += value_template % (key, val)
                elif isinstance(val, (int, long)):
                    valuestr += value_template % (key, val)
            towrite = file_template % {'values':valuestr}
            if os.path.isfile(self.name):
                current = open(self.name).read()
                if current == towrite:
                    debug("%s - up to date, skipping", self.name)
                    return
            f = open(self.name, 'w')
            f.write(towrite)
            f.close()
    cfg = ConfigH(fn.__name__)
    fn(cfg)
    cfg.write()
    return None
