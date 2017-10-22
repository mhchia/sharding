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
    R0
    B1
    RC0
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


LEN_HASH = 8
NUM_TX_IN_BLOCK = 3
EMPTY_TX = '&nbsp;' * 4

def draw_struct(g, prev_hash, current_hash, height, txs, struct_type='block'):
    assert len(txs) <= NUM_TX_IN_BLOCK
    # if len(prev_hash) > LEN_HASH:
    #     prev_hash = prev_hash[:LEN_HASH]
    # if len(current_hash) > LEN_HASH:
    #     current_hash = current_hash[:LEN_HASH]
    assert isinstance(height, int)
    hash_label = '<hash> {} {}:\n {}'.format(struct_type, height, current_hash)
    prev_label = '<prev> prev: \n {}'.format(prev_hash)
    txs_label = '{'
    for i in range(NUM_TX_IN_BLOCK):
        txs_label += '<tx{}> '.format(i)
        if i >= len(txs):
            txs_label += EMPTY_TX
        else:
            txs_label += txs[i]
        if i != NUM_TX_IN_BLOCK - 1:
            txs_label += ' | '
    txs_label += '}'
    label = '{ %s | %s | %s }' % (hash_label, txs_label, prev_label)
    shape = 'Mrecord' if struct_type == 'collation' else 'record'
    g.node(current_hash, label, shape=shape)
    # if height != 0:
    g.edge(current_hash, prev_hash)


# draw period
layers = {}
mainchain_caption = "mainchain"
g.node(mainchain_caption, shape='none')
layers[mainchain_caption] = []
# for i in range(expected_period_number + 1):
#     name = str(i)
#     g.edge(name, prev)
#     g.node(name, label=name, shape='box')
#     layers[name] = []
#     prev = name

chain = tl.get_tester_chain().chain
current_block = chain.head

while current_block is not None:
    # draw head
    prev_block = chain.get_parent(current_block)
    if prev_block is None:
        prev_block_hash = mainchain_caption
    else:
        prev_block_hash = prev_block.header.hash.hex()[:LEN_HASH]
    current_block_hash = current_block.header.hash.hex()[:LEN_HASH]
    # print("!@# {}: {}".format(current_block.header.number, current_block_hash))
    draw_struct(
        g,
        prev_block_hash,
        current_block_hash,
        current_block.header.number,
        [],
    )
    layers[current_block_hash] = []
    current_block = prev_block


# draw collations per shard
genesis_hash = b'\x00' * 32
prefix_length = 8
for shard_id, collation_map in tl.collation_map.items():
    shardchain_caption = "shard_" + str(shard_id)
    g.node(shardchain_caption, shape='none')
    layers[mainchain_caption].append(shardchain_caption)
    for i in range(len(collation_map)):
        layer = collation_map[i]
        for j in range(len(layer)):
            collation = layer[j]
            if collation['hash'] == genesis_hash:
                continue
            else:
                label = "C{},{},{}\n\n".format(shard_id, i, j)
                name = collation['hash'].hex()[:LEN_HASH]
                label += name
            prev_name = collation['parent_collation_hash']
            if prev_name == None or prev_name == genesis_hash:
                prev_name = shardchain_caption
            else:
                prev_name = prev_name.hex()[:LEN_HASH]
            period_start_prevhash = collation['period_start_prevhash'].hex()[:LEN_HASH]
            layers[period_start_prevhash].append(name)
            # g.edge(name, prev_name)
            # g.node(name, label=label)#, shape='Mrecord')
            draw_struct(g, prev_name, name, i, [], struct_type='collation')

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
print("len(made_txs): ", len(tl.made_txs))
print(tl.receipts)
g.view()
