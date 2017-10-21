import graphviz as gv

from ethereum import utils

from sharding.testing_lang import TestingLang
from sharding.tools import tester

tl = TestingLang()
cmds = """
    D0
    B25
    C0
    B5
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
cmds = """
    D0
    B25
    C0
    B5
"""
tl.execute(cmds)
expected_period_number = tl.c.chain.get_expected_period_number()

g = gv.Digraph('G', filename='image')

# # g = gv.Digraph('G', filename='image', engine='fdp')

# # g.graph_attr['rankdir'] = 'TB'
# # g.attr(compound='true')

# # with g.subgraph(name='b0') as s:
# #     # s.attr(rank='same')
# #     # s.edges(['12', '23'])
# #     s.edge('R0', 'R1')
# # with g.subgraph(name='clustera0') as a:
# #     a.edge('a', 'b')

# # with g.subgraph(name='clusterb0') as b:
# #     b.edge('d', 'f')
# with g.subgraph(name='clusterA') as s:
#     s.node('R0')
# with g.subgraph(name='clusterB') as s:
#     s.node('C0')
# g.edge('clusterB', 'clusterA') # works in engine='fdp'
# # g.edge('clusterB1', 'clusterB0', ltail='clusterB1', lhead='clusterB0')

# #g.edge('C0', 'R0')

# print(g.source)

# g.view()
# exit(1)

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
                label = "C{},{},{}\n\n".format(shard_id, i, j)
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

def add_rank_same(g, node_list):
    rank_same_str = "\t{rank=same; "
    for node in node_list:
        rank_same_str += (g._quote(node) + '; ')
    rank_same_str += '}'
    g.body.append(rank_same_str)

# set rank
for period, labels in layers.items():
    add_rank_same(g, [period] + labels)

print(g.source)
g.view()
