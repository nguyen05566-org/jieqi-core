#!/usr/bin/env python3
"""Patch AlphaGomoku source: mở khóa CARO6 trên bàn 20x20."""
import sys

src_root = sys.argv[1] if len(sys.argv) > 1 else 'ag-src'

f = src_root + '/src/player/ProgramManager.cpp'
src = open(f).read()
old = """\t\t\t\tcase GameRules::STANDARD:
\t\t\t\tcase GameRules::RENJU:
\t\t\t\tcase GameRules::CARO5:
\t\t\t\tcase GameRules::CARO6:
\t\t\t\t\treturn board_size_equal_to(cfg, 15);"""
old = old.replace('\t', '    ')
new = """    case GameRules::STANDARD:
    case GameRules::RENJU:
        return board_size_equal_to(cfg, 15);
    case GameRules::CARO5:
    case GameRules::CARO6:
        return board_size_equal_to(cfg, 15) or board_size_equal_to(cfg, 20);"""
if old not in src:
    # thử dạng tab thật
    old_t = old.replace('    ', '\t')
    if old_t in src: old = old_t
assert old in src, 'ProgramManager pattern not found'
open(f, 'w').write(src.replace(old, new))
print('ProgramManager.cpp patched')

f = src_root + '/src/player/EngineSettings.cpp'
src = open(f).read()
old_t = '\t\tadd_path(path_to_conv_networks, GameRules::CARO5, 15, config["conv_networks"]["caro5"].getString());\n\t\tadd_path(path_to_conv_networks, GameRules::CARO6, 15, config["conv_networks"]["caro6"].getString());'
new_t = old_t + '\n\t\tadd_path(path_to_conv_networks, GameRules::CARO5, 20, config["conv_networks"]["caro5"].getString());\n\t\tadd_path(path_to_conv_networks, GameRules::CARO6, 20, config["conv_networks"]["caro6"].getString());'
old_s = old_t.replace('\t', '    ')
new_s = new_t.replace('\t', '    ')
if old_t in src:
    src = src.replace(old_t, new_t)
elif old_s in src:
    src = src.replace(old_s, new_s)
else:
    raise AssertionError('EngineSettings pattern not found')
open(f, 'w').write(src.replace(old, new) if False else src)
print('EngineSettings.cpp patched')
