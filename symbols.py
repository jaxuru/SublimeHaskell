# -*- coding: UTF-8 -*-

import html
import re
import sublime
import os.path

if int(sublime.version()) < 3000:
    from sublime_haskell_common import *
else:
    from SublimeHaskell.sublime_haskell_common import *
    from functools import reduce


class Position(object):
    def __init__(self, line, column):
        self.line = line
        self.column = column

    def __str__(self):
        return self.to_string()

    def to_string(self):
        if self.column is None:
            return str(self.line)
        return ':'.join([str(self.line), str(self.column)])

    def to_zero_based(self):
        return Position(self.line - 1, self.column - 1)

    def from_zero_based(self):
        return Position(self.line + 1, self.column + 1)


class Location(object):
    """
    Location in file at line
    """
    def __init__(self, filename, project = None):
        self.project = project
        self.filename = filename

    def __str__(self):
        return self.to_string()

    def to_string(self):
        return self.filename

    def is_null(self):
        return self.project is None and self.filename is None

    def get_id(self):
        return self.filename


def source_location(loc, pos):
    """ Returns filename:line:column """
    if not pos:
        return str(loc)
    return ':'.join([str(loc), str(pos)])


class Package(object):
    def __init__(self, name, version = None):
        self.name = name
        self.version = version

    def package_id(self):
        return '{0}-{1}'.format(self.name, self.version) if self.version is not None else self.name


def parse_package(package_id):
    if package_id is None:
        return None
    m = re.match('([\w\-]+)\-([\d\.]+)', package_id)
    if m:
        (name, version) = m.groups()
        return Package(name, version)
    m = re.match('([\w\-]+)', package_id)
    if m:
        (name, ) = m.groups()
        return Package(name)
    return None


class PackageDb(object):
    def __init__(self, global_db = False, user_db = False, package_db = None):
        self.global_db = False
        self.user_db = False
        self.package_db = None
        if global_db:
            self.global_db = True
            return
        if user_db:
            self.user_db = True
            return
        if package_db:
            self.package_db = package_db
            return

    def __str__(self):
        return self.to_string()

    def to_string(self):
        if self.global_db:
            return 'global-db'
        if self.user_db:
            return 'user-db'
        if self.package_db:
            return self.package_db

    @staticmethod
    def from_string(s):
        if s == 'global-db':
            return PackageDb(global_db = True)
        if s == 'user-db':
            return PackageDb(user_db = True)
        return PackageDb(package_db = s)


class InstalledLocation(object):
    """
    Module location in cabal
    """
    def __init__(self, package, db = PackageDb(global_db = True)):
        self.package = package
        self.db = db

    def __str__(self):
        return self.to_string()

    def to_string(self):
        return '{0} in {1}'.format(self.package.package_id(), self.db.to_string())

    def is_null(self):
        return self.package is None

    def get_id(self):
        return '{0}:{1}'.format(self.db.to_string(), self.package.package_id())

    def is_cabal(self):
        return not self.db.package_db

    def sandbox(self):
        return self.db.package_db


class OtherLocation(object):
    """
    Other module location
    """
    def __init__(self, source):
        self.source = source

    def __str__(self):
        return self.to_string()

    def to_string(self):
        return (self.source or "")

    def is_null(self):
        return self.source is None

    def get_id(self):
        return '[{0}]'.format(self.source)


def location_package_name(loc):
    if type(loc) == InstalledLocation and loc.package:
        return loc.package.name
    return None


def location_project(loc):
    if type(loc) == Location and loc.project:
        return loc.project
    return None


def location_cabal(loc):
    if type(loc) == InstalledLocation:
        return loc.cabal
    return None


class Symbol(object):
    """
    Haskell symbol: module, function, data, class etc.
    """
    def __init__(self, symbol_type, name):
        self.what = symbol_type
        self.name = name

        self.tags = {}


class Import(object):
    """
    Haskell import of module
    """
    def __init__(self, module_name, is_qualified = False, import_as = None, position = None, location = None):
        self.module = module_name
        self.is_qualified = is_qualified
        self.import_as = import_as
        self.position = position
        self.location = location

    def dump(self):
        return self.__dict__


def module_location(filename):
    return Location(filename)


class Module(Symbol):
    """
    Haskell module symbol
    """
    def __init__(self, module_name, exports = None, imports = [], declarations = {}, location = None, last_inspection_time = 0):
        super(Module, self).__init__('module', module_name)
        self.location = location
        # List of strings
        if exports is not None:
            self.exports = exports[:]
        # Dictionary from module name to Import object
        self.imports = imports[:]
        for i in self.imports:
            i.location = self.location
        # Dictionary from name to Symbol
        self.declarations = declarations.copy()
        for d in self.declarations.values():
            d.location = self.location

        for decl in self.declarations.values():
            decl.module = self

        # Time as from time.time()
        self.last_inspection_time = last_inspection_time

    def add_declaration(self, new_declaration):
        if not new_declaration.module:
            new_declaration.module = self
        new_declaration.location = self.location
        if new_declaration.module != self:
            raise RuntimeError("Adding declaration to other module")
        self.declarations[new_declaration.name] = new_declaration

    def unalias(self, module_alias):
        """
        Unalias module import if any
        Returns list of unaliased modules
        """
        return [i.module for i in self.imports if i.import_as == module_alias]

    def get_location_id(self):
        if type(self.location) == InstalledLocation:
            return '{0}:{1}'.format(self.location.get_id(), self.name)
        return self.location.get_id()

    def by_source(self):
        return type(self.location) == Location

    def by_cabal(self):
        return type(self.location) == InstalledLocation

    def by_hayoo(self):
        return type(self.location) == OtherLocation


def escape_text(txt):
    """
    Escape text, replacing leading spaces to non-breaking ones and newlines to <br> tag
    """
    lines = []
    for line in txt.splitlines():
        m = re.match(r'^\s+', line)
        if m:  # Replace leading spaces with non-breaking ones
            lines.append(m.end() * '&nbsp;' + html.escape(line[m.end():], quote = False))
        else:
            lines.append(html.escape(line, quote = False))

    return '<br>'.join(lines)


class Declaration(Symbol):
    def __init__(self, name, decl_type = 'declaration', docs = None, imported = [], defined = None, position = None, module = None):
        super(Declaration, self).__init__(decl_type, name)
        self.docs = docs
        self.imported = imported[:]
        self.defined = defined
        self.position = position
        self.module = module

    def defined_module(self):
        return self.defined or self.module

    def by_source(self):
        return type(self.defined_module().location) == Location

    def by_cabal(self):
        return type(self.defined_module().location) == InstalledLocation

    def by_hayoo(self):
        return type(self.defined_module().location) == OtherLocation

    def has_source_location(self):
        return self.by_source() and self.position is not None

    def get_source_location(self):
        if self.has_source_location():
            return source_location(self.defined_module().location, self.position)
        return None

    def make_qualified(self):
        self.name = self.qualified_name()

    def module_name(self):
        if self.imported:
            return self.imported[0].module
        return self.module.name

    def imported_names(self):
        if self.imported:
            return sorted(list(set([i.module for i in self.imported])))
        # if self.module:
        #     return [self.module.name]
        return []

    def imported_from_name(self):
        inames = self.imported_names()
        if inames:
            return self.imported_names()[0]
        return ''

    def suggest(self):
        """ Returns suggestion for this declaration """
        return ('{0}\t{1}'.format(self.name, self.imported_from_name()), self.name)

    def brief(self, short = False):
        """ Brief information, just a name by default """
        return self.name

    def qualified_name(self):
        return '.'.join([self.module_name(), self.name])

    def detailed(self):
        """ Detailed info for use in Symbol Info command """
        parts = [self.brief()]

        if self.imported_names():
            parts.extend(['', 'Imported from {0}'.format(', '.join(self.imported_names()))])

        if self.docs:
            parts.extend(['', self.docs])

        parts.append('')

        if self.by_source():
            if self.defined_module().location.project:
                parts.append('Project: {0}'.format(self.defined_module().location.project))
        elif self.by_cabal():
            parts.append('Installed in: {0}'.format(self.defined_module().location.db.to_string()))
            parts.append('Package: {0}'.format(self.defined_module().location.package.package_id()))

        if self.has_source_location():
            parts.append('Defined at: {0}'.format(self.get_source_location()))
        else:
            parts.append('Defined in: {0}'.format(self.defined_module().name))

        return '\n'.join(parts)

    def popup_brief(self):
        """ Brief info on popup with name, possibly with link if have source location """
        info = u'<span class="function">{0}</span>'.format(html.escape(self.name, quote = False))
        if self.has_source_location():
            return u'<a href="{0}">{1}</a>'.format(html.escape(self.get_source_location()), info)
        else:
            return info

    def popup(self):
        """ Full info on popup with docs """
        parts = [u'<p>']
        parts.append(self.popup_brief())
        if self.imported_names():
            parts.append(u'<br>{0}<span class="comment">-- Imported from {1}</span>'.format(
                4 * '&nbsp;',
                html.escape(u', '.join(self.imported_names()), quote = False)))
        if self.defined_module():
            module_ref = html.escape(self.defined_module().name, quote = False)
            if self.defined_module().by_source():
                module_ref = u'<a href="{0}">{1}</a>'.format(self.defined_module().location.to_string(), module_ref)
            elif self.defined_module().by_cabal():
                hackage_url = 'http://hackage.haskell.org/package/{0}/docs/{1}.html'.format(
                    self.defined_module().location.package.package_id(),
                    self.defined_module().name.replace('.', '-'))
                module_ref = u'<a href="{0}">{1}</a>'.format(html.escape(hackage_url), module_ref)
            parts.append(u'<br>{0}<span class="comment">-- Defined in {1}</span>'.format(
                4 * '&nbsp;',
                module_ref))
        parts.append(u'</p>')
        if self.docs:
            parts.append(u'<p><span class="docs">{0}</span></p>'.format(escape_text(self.docs)))
        # parts.append(u'<a href="info">...</a>')
        return u''.join(parts)


def wrap_operator(name):
    if re.match(r"[\w']+", name):
        return name
    return "({0})".format(name)


def format_type(expr):
    """
    Format type expression for popup
    Set span 'type' for types and 'tyvar' for type variables
    """

    if not expr:
        return expr
    m = re.search(r'([a-zA-Z]\w*)|(->|=>|::)', expr)
    if m:
        e = expr[m.start():m.end()]
        expr_class = ''
        if m.group(1):
            expr_class = 'type' if e[0].isupper() else 'tyvar'
        elif m.group(2):
            expr_class = 'operator'
        decorated = '<span class="{0}">{1}</span>'.format(expr_class, html.escape(e, quote = False))
        return html.escape(expr[0:m.start()], quote = False) + decorated + format_type(expr[m.end():])
    else:
        return html.escape(expr, quote = False)


class Function(Declaration):
    """
    Haskell function declaration
    """
    def __init__(self, name, function_type, docs = None, imported = [], defined = None, position = None, module = None):
        super(Function, self).__init__(name, 'function', docs, imported, defined, position, module)
        self.type = function_type

    def suggest(self):
        return (u'{0} :: {1}\t{2}'.format(wrap_operator(self.name), self.type, self.imported_from_name()), self.name)

    def brief(self, short = False):
        if short:
            return u'{0}'.format(wrap_operator(self.name))
        return u'{0} :: {1}'.format(wrap_operator(self.name), self.type if self.type else u'?')

    def popup_brief(self):
        info = u'<span class="function">{0}</span>'.format(html.escape(self.name, quote = False))
        if self.has_source_location():
            info = u'<a href="{0}">{1}</a>'.format(html.escape(self.get_source_location()), info)
        return u'{0} <span class="operator">::</span> {1}'.format(info, format_type(self.type if self.type else u'?'))


class TypeBase(Declaration):
    """
    Haskell type, data or class
    """
    def __init__(self, name, decl_type, context, args, definition = None, docs = None, imported = [], defined = None, position = None, module = None):
        super(TypeBase, self).__init__(name, decl_type, docs, imported, defined, position, module)
        self.context = context
        self.args = args
        self.definition = definition

    def suggest(self):
        return (u'{0} {1}\t{2}'.format(self.name, ' '.join(self.args), self.imported_from_name()), self.name)

    def brief(self, short = False):
        if short:
            brief_parts = [self.what, self.name]
            if self.args:
                brief_parts.extend(self.args)
            return u' '.join(brief_parts)

        if self.definition:
            return self.definition

        brief_parts = [self.what]
        if self.context:
            if len(self.context) == 1:
                brief_parts.append(u'{0} =>'.format(self.context[0]))
            else:
                brief_parts.append(u'({0}) =>'.format(', '.join(self.context)))

        brief_parts.append(self.name)
        if self.args:
            brief_parts.append(u' '.join(self.args))

        return u' '.join(brief_parts)

    def popup_brief(self):
        parts = [u'<span class="keyword">{0}</span>'.format(html.escape(self.what, quote = False))]
        if self.context:
            ctx = self.context.split(', ')
            if len(ctx) == 1:
                parts.append(format_type(u'{0} =>'.format(ctx[0])))
            else:
                parts.append(format_type(u'({0}) =>'.format(', '.join(ctx))))

        name_part = u'<span class="type">{0}</span>'.format(html.escape(self.name, quote = False))
        if self.has_source_location():
            name_part = u'<a href="{0}">{1}</a>'.format(html.escape(self.get_source_location()), name_part)
        parts.append(name_part)

        if self.args:
            parts.append(format_type(u' '.join(self.args)))

        return u' '.join(parts)


class Type(TypeBase):
    """
    Haskell type synonym
    """
    def __init__(self, name, context, args, definition = None, docs = None, imported = [], defined = None, position = None, module = None):
        super(Type, self).__init__(name, 'type', context, args, definition, docs, imported, defined, position, module)


class Newtype(TypeBase):
    """
    Haskell newtype synonym
    """
    def __init__(self, name, context, args, definition = None, docs = None, imported = [], defined = None, position = None, module = None):
        super(Newtype, self).__init__(name, 'newtype', context, args, definition, docs, imported, defined, position, module)


class Data(TypeBase):
    """
    Haskell data declaration
    """
    def __init__(self, name, context, args, definition = None, docs = None, imported = [], defined = None, position = None, module = None):
        super(Data, self).__init__(name, 'data', context, args, definition, docs, imported, defined, position, module)


class Class(TypeBase):
    """
    Haskell class declaration
    """
    def __init__(self, name, context, args, definition = None, docs = None, imported = [], defined = None, position = None, module = None):
        super(Class, self).__init__(name, 'class', context, args, definition, docs, imported, defined, position, module)


def update_with(l, r, default_value, f):
    """
    unionWith for Python, but modifying first dictionary instead of returning result
    """
    for k, v in r.items():
        if k not in l:
            l[k] = default_value[:]
        l[k] = f(l[k], v)
    return l


def same_module(l, r):
    """
    Returns true if l is same module as r, which is when module name is equal
    and modules defined in one file, in same cabal-dev sandbox or in cabal
    """
    same_cabal = l.cabal and r.cabal and (l.cabal == r.cabal)
    same_filename = l.location and r.location and (l.location.filename == r.location.filename)
    nowhere = (not l.cabal) and (not l.location) and (not r.cabal) and (not r.location)
    return l.name == r.name and (same_cabal or same_filename or nowhere)


def same_declaration(l, r):
    """
    Returns true if l is same declaration as r
    """
    same_mod = l.module and r.module and same_module(l.module, r.module)
    nowhere = (not l.module) and (not r.module)
    return l.name == r.name and (same_mod or nowhere)


def is_within_project(module, project):
    """
    Returns whether module defined within project specified
    """
    if module.location:
        return module.location.project == project
    return False


def is_within_cabal(module, cabal = None):
    """
    Returns whether module loaded from cabal specified
    """
    return cabal is not None and module.cabal == cabal


def is_by_sources(module):
    """
    Returns whether module defined by sources
    """
    return module.location is not None


def flatten(lsts):
    return reduce(lambda l, r: list(l) + list(r), lsts)


class CabalPackage(object):
    def __init__(self, name, synopsis = None, version = None, installed = [], homepage = None, license = None):
        self.name = name
        self.synopsis = synopsis
        self.default_version = version
        self.installed_versions = installed[:]
        self.homepage = homepage
        self.license = license

    def brief(self):
        return self.name

    def detailed(self):
        info = []
        info.append(self.brief())
        info.append('')
        if self.synopsis:
            info.append(self.synopsis)
            info.append('')
        if self.default_version:
            info.append('Last version: ' + self.default_version)
        if self.installed_versions:
            info.append('Installed versions: ' + ", ".join(self.installed_versions))
        if self.homepage:
            info.append('Homepage: ' + self.homepage)
        if self.license:
            info.append('License: ' + self.license)

        return '\n'.join(info)


class Corrector(object):
    def __init__(self, start, end, contents):
        self.start = start
        self.end = end
        self.contents = contents

    def to_region(self, view):
        return sublime.Region(view.text_point(self.start.line, self.start.column), view.text_point(self.end.line, self.end.column))


class Correction(object):
    def __init__(self, file, level, message, corrector):
        self.file = file
        self.level = level
        self.message = message
        self.corrector = corrector

    def to_region(self, view):
        return self.corrector.to_region(view)


def mark_corrections(views, corrs):
    for view in views:
        if view.file_name() is None:
            continue
        corrs_ = [corr for corr in corrs if os.path.samefile(corr.file, view.file_name())]
        view.add_regions('autofix', [corr.to_region(view) for corr in corrs_], 'entity.name.function', 'dot', 0)
