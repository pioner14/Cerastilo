"""libxml2 2.9.14 для lxml 6 (штатный рецепт p4a — 2.9.12, см. ../README.md)."""
from os.path import dirname, join

from pythonforandroid.recipes import libxml2 as upstream

# Патч и glob.c берём из штатного рецепта: путь абсолютный, поэтому
# Recipe.apply_patch не ищет его в этой папке
_UPSTREAM_DIR = dirname(upstream.__file__)


class Libxml2Recipe(upstream.Libxml2Recipe):
    version = '2.9.14'
    url = 'https://download.gnome.org/sources/libxml2/2.9/libxml2-{version}.tar.xz'
    md5sum = 'b7b3029ac6beb32a7925225515f83ca3'
    patches = [join(_UPSTREAM_DIR, 'add-glob.c.patch')]


recipe = Libxml2Recipe()
