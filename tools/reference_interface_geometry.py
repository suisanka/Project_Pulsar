"""Reference STL alignment, vent-boundary extraction and smooth interface trim guide. Coordinates are millimetres. No headform or fit transform is used."""
import json
from pathlib import Path
import numpy as np

def load_aligned(stl, registration):
    data = Path(stl).read_bytes()
    count = int.from_bytes(data[80:84], 'little')
    if len(data) != 84 + 50 * count:
        raise ValueError('Expected binary STL')
    records = np.frombuffer(data, dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')], offset=84)
    v, indices = np.unique(records['v'].reshape(-1, 3), axis=0, return_inverse=True)
    pose = json.loads(Path(registration).read_text())['registration_for_comparison_only']
    return (v.astype(float) @ np.array(pose['rotation_matrix']).T + pose['translation_mm'], indices.reshape(-1, 3))

def vent_annuli(v, f, threshold=0.65):
    p = v[f]
    normals = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    centers = p.mean(1)
    radial = centers - [0, -5, 10]
    radial /= np.linalg.norm(radial, axis=1)[:, None]
    dot = np.sum(normals * radial, axis=1)
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    ids = np.tile(np.arange(len(f)), 3)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges, ids = (edges[order], ids[order])
    if not np.array_equal(edges[::2], edges[1::2]):
        raise ValueError('Source must have exactly two faces per edge')
    pairs = np.column_stack([ids[::2], ids[1::2]])
    mask = abs(dot) < threshold
    parent = np.arange(len(f))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in pairs[mask[pairs].all(1)]:
        parent[root(a)] = root(b)
    groups = {}
    for i in np.flatnonzero(mask):
        groups.setdefault(root(i), []).append(i)
    result = []
    for group in groups.values():
        if len(group) < 10:
            continue
        group = np.array(group)
        faces = f[group]
        directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        e, inverse, counts = np.unique(np.sort(directed, axis=1), axis=0, return_inverse=True, return_counts=True)
        border_directed = directed[counts[inverse] == 1]
        adjacency = {}
        for a, b in border_directed:
            adjacency.setdefault(int(a), []).append(int(b))
            adjacency.setdefault(int(b), []).append(int(a))
        if not adjacency or any((len(neighbors) != 2 for neighbors in adjacency.values())):
            continue
        unseen, loops = (set(adjacency), [])
        directed_keys = {tuple(e) for e in border_directed}
        while unseen:
            start, previous = (min(unseen), -1)
            current, loop = (start, [])
            while True:
                loop.append(current)
                unseen.remove(current)
                following = next((n for n in adjacency[current] if n != previous))
                previous, current = (current, following)
                if current == start:
                    break
            if (loop[0], loop[1]) not in directed_keys:
                loop.reverse()
            loops.append(loop)
        size = np.ptp(v[faces], axis=(0, 1))
        if len(loops) == 2 and max(size) < 35:
            result.append({'faces': group, 'loops': loops, 'center': centers[group].mean(0), 'size': size})
    return (result, dot)

def hermite(z, x, y):
    x = np.array(x, float)
    y = np.array(y, float)
    d = np.gradient(y, x)
    z = np.asarray(z)
    i = np.clip(np.searchsorted(x, z) - 1, 0, len(x) - 2)
    t = np.clip((z - x[i]) / (x[i + 1] - x[i]), 0, 1)
    h = x[i + 1] - x[i]
    return (2 * t ** 3 - 3 * t * t + 1) * y[i] + (t ** 3 - 2 * t * t + t) * h * d[i] + (-2 * t ** 3 + 3 * t * t) * y[i + 1] + (t ** 3 - t * t) * h * d[i + 1]

def seam(z):
    return hermite(z, [-100, -90, -80, -70, -60, -50, -40, -30, -20, -10, 0, 10, 30, 50, 80, 110, 130, 140, 150, 165], [-80, -56, -28, -24, -26, -29, -32.5, -35, -36, -35, -30, -24, -12, 0, 19, 38, 54, 60, 50, 0])

def width(z):
    return hermite(z, [-100, -10, 0, 15, 30, 50, 80, 165], [10, 10, 10, 25, 35, 35, 20, 20])

def warp(v):
    p = v.copy()
    p[:, 1] = (p[:, 1] - seam(p[:, 2])) / width(p[:, 2]) * 20
    return p
