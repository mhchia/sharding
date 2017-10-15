import graphviz as gv

from ethereum import utils

from sharding.testing_lang import TestingLang
from sharding.tools import tester

tl = TestingLang()
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
"""
tl.execute(cmds)
expected_period_number = tl.c.chain.get_expected_period_number()

g = gv.Digraph('G', filename='image')

# draw period
layers = {}
prev = "period"
layers[prev] = []
for i in range(expected_period_number + 1):
    g.edge(str(i), prev)
    layers[str(i)] = []
    prev = str(i)

# draw collations per shard
genesis_hash = b'\x00' * 32
for shard_id, collation_map in tl.collation_map.items():
    first_label = "shard_" + str(shard_id)
    layers["period"].append(first_label)
    for layer in collation_map:
        for collation in layer:
            label = collation['hash']
            if label == genesis_hash:
                continue
            else:
                label = label.hex()[:8]
            prev_label = collation['parent_collation_hash']
            if prev_label == None or prev_label == genesis_hash:
                prev_label = first_label
            else:
                prev_label = prev_label.hex()[:8]
            layers[str(collation['period'])].append(label)
            g.edge(label, prev_label)

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
