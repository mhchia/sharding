import graphviz as gv

from ethereum import utils

from sharding.testing_lang import TestingLang
from sharding.tools import tester

tl = TestingLang()
cmds = """
    D0 # deposit validator 0
    W0 # withdraw validator 0
    D0
    B5
    C0
    B1
    C0
    B1
    C0
    B5
    C0
    B1
    C0
    B5
    C0
    B1
    C0
    B1
    C0,0,0
    C0,1,0
    C1,0,0
#####   C2,1,0  # Error: no corresponding parent
"""
cmds = """
    D0
    B5
    C0
    C0,0,0
    B5
    C0,1,0
    B5
    C0,1,1
    # C0
    B5
    C1
    B5
    C0,2,1
"""
tl.execute(cmds)
expected_period_number = tl.c.chain.get_expected_period_number()

g = gv.Digraph('G', filename='image')

# draw period
layers = {}
prev = "period"
g.node(prev, label=prev, shape='box')
layers[prev] = []
for i in range(expected_period_number + 1):
    name = str(i)
    g.edge(name, prev)
    g.node(name, label=name, shape='box')
    layers[name] = []
    prev = name

# draw collations per shard
genesis_hash = b'\x00' * 32
prefix_length = 8
for shard_id, collation_map in tl.collation_map.items():
    first_name = "shard_" + str(shard_id)
    layers["period"].append(first_name)
    for i in range(len(collation_map)):
        layer = collation_map[i]
        for j in range(len(layer)):
            collation = layer[j]
            if collation['hash'] == genesis_hash:
                continue
            else:
                label = "C({}, {})\n\n".format(i, j)
                name = collation['hash'].hex()[:prefix_length]
                label += name
            prev_name = collation['parent_collation_hash']
            if prev_name == None or prev_name == genesis_hash:
                prev_name = first_name
            else:
                prev_name = prev_name.hex()[:prefix_length]
            layers[str(collation['period'])].append(name)
            g.edge(name, prev_name)
            g.node(name, label=label)#, shape='Mrecord')

# set rank
for period, labels in layers.items():
    rank_same_str = "\t{rank=same; "
    rank_same_str += (period + '; ')
    for label in labels:
        rank_same_str += (g._quote(label) + '; ')
    rank_same_str += '}'
    g.body.append(rank_same_str)

print(g.source)
g.view()
