#!/usr/bin/env python3
"""Patch AlphaGomoku v5.9.3: mo khoa CARO5/CARO6 tren ban 20x20.

1) ProgramManager::is_game_config_correct() - v5.9.3 chi cho CARO5/CARO6
   tren 15 -> them nhanh 20.
2) EngineSettings - dang ky network CARO5/20 va CARO6/20 (mac dinh chi 15).
"""
import sys

src_root = (sys.argv[1] if len(sys.argv) > 1 else 'ag-src').rstrip('/')

# ---------- Patch 1: ProgramManager.cpp ----------
f = src_root + '/src/player/ProgramManager.cpp'
src = open(f).read()

if 'CARO6:' in src and 'return board_size_equal_to(cfg, 15) or board_size_equal_to(cfg, 20);' in src:
    print('ProgramManager: da co CARO6/20 - bo qua')
else:
    done = False
    for case_indent, ret_indent in (('\t\t\t', '\t\t\t\t'), ('            ', '                ')):
        old = ('case GameRules::STANDARD:\n'
               + case_indent + 'case GameRules::RENJU:\n'
               + case_indent + 'case GameRules::CARO5:\n'
               + case_indent + 'case GameRules::CARO6:\n'
               + ret_indent + 'return board_size_equal_to(cfg, 15);')
        new = ('case GameRules::STANDARD:\n'
               + case_indent + 'case GameRules::RENJU:\n'
               + ret_indent + 'return board_size_equal_to(cfg, 15);\n'
               + case_indent + 'case GameRules::CARO5:\n'
               + case_indent + 'case GameRules::CARO6:\n'
               + ret_indent + 'return board_size_equal_to(cfg, 15) or board_size_equal_to(cfg, 20);')
        if old in src:
            src = src.replace(old, new)
            print('ProgramManager patched')
            done = True
            break
    if not done:
        raise AssertionError('ProgramManager pattern not found (15-only CARO block)')
    open(f, 'w').write(src)

# ---------- Patch 2: EngineSettings.cpp ----------
f = src_root + '/src/player/EngineSettings.cpp'
src = open(f).read()

if 'GameRules::CARO6, 20,' in src:
    print('EngineSettings: da co CARO6/20 - bo qua')
else:
    caro5_15 = 'add_path(path_to_conv_networks, GameRules::CARO5, 15, config["conv_networks"]["caro5"].getString());'
    caro6_15 = 'add_path(path_to_conv_networks, GameRules::CARO6, 15, config["conv_networks"]["caro6"].getString());'
    assert caro5_15 in src and caro6_15 in src, 'add_path lines not found'
    indent = ''
    for line in src.splitlines():
        if caro6_15 in line:
            indent = line[:len(line) - len(line.lstrip())]
            break
    src = src.replace(caro5_15, caro5_15 + '\n' + indent + 'add_path(path_to_conv_networks, GameRules::CARO5, 20, config["conv_networks"]["caro5"].getString());')
    src = src.replace(caro6_15, caro6_15 + '\n' + indent + 'add_path(path_to_conv_networks, GameRules::CARO6, 20, config["conv_networks"]["caro6"].getString());')
    open(f, 'w').write(src)
    print('EngineSettings patched: CARO5/20 + CARO6/20 registered')
