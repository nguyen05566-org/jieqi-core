#!/usr/bin/env python3
"""Patch AlphaGomoku v5.9.3: đăng ký network CARO5/CARO6 cho bàn 20x20.
ProgramManager v5.9.3 đã cho phép CARO5/CARO6 trên 15 hoặc 20 — chỉ thiếu
entry network trong EngineSettings (CARO6 chỉ đăng ký cho 15)."""
import sys

src_root = (sys.argv[1] if len(sys.argv) > 1 else 'ag-src').rstrip('/')
f = src_root + '/src/player/EngineSettings.cpp'
src = open(f).read()

caro5_15 = 'add_path(path_to_conv_networks, GameRules::CARO5, 15, config["conv_networks"]["caro5"].getString());'
caro6_15 = 'add_path(path_to_conv_networks, GameRules::CARO6, 15, config["conv_networks"]["caro6"].getString());'

indent = ''
for line in src.splitlines():
    if caro6_15 in line:
        indent = line[:len(line) - len(line.lstrip())]
        break
assert indent, 'caro6 add_path line not found'

extra_caro5_20 = indent + 'add_path(path_to_conv_networks, GameRules::CARO5, 20, config["conv_networks"]["caro5"].getString());'
extra_caro6_20 = indent + 'add_path(path_to_conv_networks, GameRules::CARO6, 20, config["conv_networks"]["caro6"].getString());'

if 'GameRules::CARO6, 20,' in src:
    print('CARO6/20 da co san - khong can patch')
else:
    assert caro5_15 in src and caro6_15 in src, 'add_path lines not found'
    src = src.replace(caro5_15, caro5_15 + '\n' + extra_caro5_20)
    src = src.replace(caro6_15, caro6_15 + '\n' + extra_caro6_20)
    open(f, 'w').write(src)
    print('EngineSettings patched: CARO5/20 + CARO6/20 registered')
