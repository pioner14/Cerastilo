"""lxml 6.1.3 под Python 3.14 (штатный рецепт p4a — 4.8.0, см. ../README.md)."""
from pythonforandroid.recipes import lxml as upstream


class LXMLRecipe(upstream.LXMLRecipe):
    version = '6.1.3'
    url = 'https://files.pythonhosted.org/packages/source/l/lxml/lxml-{version}.tar.gz'
    md5sum = '15ecfaf666e0a881667005cc96e0a343'


recipe = LXMLRecipe()
