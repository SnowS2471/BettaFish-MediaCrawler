# -*- coding: utf-8 -*-
"""
南非新闻网站解析器
"""

from .base_parser import BaseNewsParser
from .mg_parser import MGParser
from .iol_parser import IOLParser
from .sowetan_parser import SowetanParser
from .news24_parser import News24Parser
from .sundaytimes_parser import SundayTimesParser

PARSER_MAP = {
    "mg": MGParser,
    "iol": IOLParser,
    "sowetan": SowetanParser,
    "news24": News24Parser,
    "sundaytimes": SundayTimesParser,
}
