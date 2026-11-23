# -*- coding: utf-8 -*-
"""
Roda DENTRO do Blender (sem janela, só CPU):

  blender -b --factory-startup -P pipeline/blender_scene.py -- \
      --timeline build/timeline.json --scene 1 --start 0 --end 150 --out frames

Tudo é gerado por código (sem baixar modelo nenhum): corpos "esculpidos" por seções
(loft) com facetas low-poly, cores por face, nadadeiras, dentes, olhos, cenário
com terreno/água/árvores/algas e névoa de profundidade.
"""
import argparse
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Vector, noise

FPS = 30
MAT = {}


# ============================================================ utilidades de cor / matemática
def lin(h, a=1.0):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def f(x):
        return ((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92
    return (f(c[0]), f(c[1]), f(c[2]), a)


def mixc(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


def scale_c(c, k):
    return (min(c[0] * k, 1.0), min(c[1] * k, 1.0), min(c[2] * k, 1.0), c[3])


def clamp01(x):
    return max(0.0, min(1.0, x))


def smooth(e0, e1, x):
    t = clamp01((x - e0) / (e1 - e0))
    return t * t * (3 - 2 * t)


def noise2(x, y, s=0.1, z=0.0):
    return noise.noise(Vector((x * s, y * s, z)))


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # detalhe decorativo nunca derruba o render
        print("AVISO (ignorado) em %s: %r" % (getattr(fn, "__name__", "?"), e))
        return None


def curve(ctrl, x):
    """Catmull-Rom sobre [(x, y), ...] em ordem crescente de x."""
    n = len(ctrl)
    if x <= ctrl[0][0]:
        return ctrl[0][1]
    if x >= ctrl[-1][0]:
        return ctrl[-1][1]
    i = 0
    while i < n - 2 and x > ctrl[i + 1][0]:
        i += 1
    x0, y1 = ctrl[i]
    x1, y2 = ctrl[i + 1]
    t = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
    y0 = ctrl[i - 1][1] if i > 0 else y1
    y3 = ctrl[i + 2][1] if i + 2 < n else y2
    return 0.5 * ((2 * y1) + (-y0 + y2) * t + (2 * y0 - 5 * y1 + 4 * y2 - y3) * t * t
                  + (-y0 + 3 * y1 - 3 * y2 + y3) * t ** 3)


def sample_prof(tab, m, a0, a1, origin):
    """tab: [(a, ry, rz, cz)] crescente em a. Devolve m seções (a, cu, cv, ru, rv) entre a0 e a1."""
    ctr = [[(r[0], r[i]) for r in tab] for i in (1, 2, 3)]
    minr = 0.0015 * abs(tab[-1][0] - tab[0][0])
    out = []
    for k in range(m):
        a = a0 + (a1 - a0) * (k / (m - 1.0))
        ry = max(curve(ctr[0], a), minr)
        rz = max(curve(ctr[1], a), minr)
        cz = curve(ctr[2], a)
        out.append((a - origin, 0.0, cz, ry, rz))
    return out


# ============================================================ funções de cor por face
def cf_animal(back, belly, spread=0.07, belly_at=-0.2):
    def f(c, nv, rnd):
        t = smooth(belly_at - 0.25, belly_at + 0.25, nv.z)
        return scale_c(mixc(belly, back, t), 1.0 + rnd.uniform(-spread, spread))
    return f


def cf_flat(col, spread=0.06):
    def f(c, nv, rnd):
        return scale_c(col, 1.0 + rnd.uniform(-spread, spread))
    return f


# ============================================================ malhas
def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def empty(name, parent=None, loc=(0.0, 0.0, 0.0)):
    ob = link(bpy.data.objects.new(name, None))
    if parent is not None:
        ob.parent = parent
    ob.location = loc
    return ob


def mesh_obj(name, me, parent=None, loc=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), scale=None):
    ob = link(bpy.data.objects.new(name, me))
    if parent is not None:
        ob.parent = parent
    ob.location = loc
    ob.rotation_euler = rot
    if scale is not None:
        ob.scale = scale
    return ob


def finish(bm, name, cfn, mat, rnd):
    col = bm.loops.layers.color.new("Col")
    for f in bm.faces:
        c = f.calc_center_median()
        rgba = cfn(c, f.normal, rnd) if cfn else (0.5, 0.5, 0.5, 1.0)
        for lp in f.loops:
            lp[col] = rgba
        f.smooth = False
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if mat is not None:
        me.materials.append(mat)
    return me


def loft_me(name, secs, n=10, axis="X", cfn=None, mat=None, caps=(True, True), jit=0.0, seed=1):
    """Corpo por seções: secs = [(a, cu, cv, ru, rv)]. axis X: anel no plano YZ. axis Z: anel no plano XY."""
    rnd = random.Random(seed)
    bm = bmesh.new()
    rings = []
    for (a, cu, cv, ru, rv) in secs:
        ring = []
        for i in range(n):
            ang = 2.0 * math.pi * i / n
            u = cu + ru * math.cos(ang)
            v = cv + rv * math.sin(ang)
            co = Vector((a, u, v)) if axis == "X" else Vector((u, v, a))
            if jit:
                co = co + Vector((rnd.uniform(-jit, jit), rnd.uniform(-jit, jit), rnd.uniform(-jit, jit)))
            ring.append(bm.verts.new(co))
        rings.append(ring)
    for j in range(len(rings) - 1):
        r0, r1 = rings[j], rings[j + 1]
        for i in range(n):
            k = (i + 1) % n
            try:
                bm.faces.new((r0[i], r0[k], r1[k], r1[i]))
            except ValueError:
                pass
    if caps[0]:
        bm.faces.new(rings[0])
    if caps[1]:
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return finish(bm, name, cfn, mat, rnd)


def slab_me(name, pts, th, plane="XY", w=None, cfn=None, mat=None, seed=1):
    """Placa fina (nadadeira / cauda): contorno 2D com espessura que afina nas pontas."""
    rnd = random.Random(seed)
    bm = bmesh.new()
    n = len(pts)
    w = w or [1.0] * n
    top, bot = [], []
    for (x, y), wi in zip(pts, w):
        t = th * max(wi, 0.12)
        if plane == "XY":
            top.append(bm.verts.new((x, y, t)))
            bot.append(bm.verts.new((x, y, -t)))
        else:
            top.append(bm.verts.new((x, t, y)))
            bot.append(bm.verts.new((x, -t, y)))
    bm.faces.new(top)
    bm.faces.new(bot[::-1])
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new((top[i], top[j], bot[j], bot[i]))
        except ValueError:
            pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    return finish(bm, name, cfn, mat, rnd)


def taper_w(pts, span):
    return [max(0.22, 1.0 - math.hypot(x, y) / span) for (x, y) in pts]


def blob_me(name, r, cfn, n=7, rings=4, jit=0.0, seed=1, mat=None, squash=1.0):
    secs = []
    for k in range(rings + 1):
        a = -r + 2.0 * r * k / rings
        rad = r * math.sqrt(max(0.0, 1.0 - (a / r) ** 2))
        secs.append((a, 0.0, 0.0, max(rad, r * 0.02), max(rad * squash, r * 0.02)))
    return loft_me(name, secs, n=n, axis="X", cfn=cfn, mat=mat if mat is not None else MAT["vc"],
                   caps=(True, True), jit=jit, seed=seed)


def cone_me(name, r, h, n=5, sign=1.0, cfn=None, seed=1):
    secs = [(0.0, 0.0, 0.0, r, r), (sign * h, 0.0, 0.0, r * 0.05, r * 0.05)]
    return loft_me(name, secs, n=n, axis="Z", cfn=cfn or cf_flat(lin("#f4f1e6")), mat=MAT["vc"],
                   caps=(True, False), seed=seed)


def terrain(name, x0, x1, y0, y1, cell, hfn, cfn, mat, seed=3):
    rnd = random.Random(seed)
    nx = max(2, int((x1 - x0) / cell))
    ny = max(2, int((y1 - y0) / cell))
    bm = bmesh.new()
    vs = []
    for i in range(nx + 1):
        row = []
        for j in range(ny + 1):
            x = x0 + (x1 - x0) * i / nx
            y = y0 + (y1 - y0) * j / ny
            row.append(bm.verts.new((x, y, hfn(x, y))))
        vs.append(row)
    for i in range(nx):
        for j in range(ny):
            bm.faces.new((vs[i][j], vs[i + 1][j], vs[i + 1][j + 1], vs[i][j + 1]))
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    me = finish(bm, name, cfn, mat, rnd)
    return mesh_obj(name, me)


# ============================================================ materiais / mundo / câmera / luz
def init_materials():
    MAT.clear()
    m = bpy.data.materials.new("vc")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = "Col"
    nt.links.new(vc.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.9
    for nm in ("Specular IOR Level", "Specular"):
        if nm in b.inputs:
            b.inputs[nm].default_value = 0.12
            break
    MAT["vc"] = m

    e = bpy.data.materials.new("emit")
    e.use_nodes = True
    nt = e.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    em.inputs["Strength"].default_value = 3.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    MAT["emit"] = e


def emit_material(name, color, strength):
    e = bpy.data.materials.new(name)
    e.use_nodes = True
    nt = e.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return e


def water_material(name, color, alpha, rough=0.12):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = color
    b.inputs["Alpha"].default_value = alpha
    b.inputs["Roughness"].default_value = rough
    return m


def reset_scene(W, H, samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scn = bpy.context.scene
    r = scn.render
    r.engine = 'CYCLES'
    r.resolution_x, r.resolution_y, r.resolution_percentage = W, H, 100
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGB'
    r.image_settings.compression = 15
    r.fps = FPS
    r.use_persistent_data = True
    c = scn.cycles
    c.device = 'CPU'
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.04
    c.use_denoising = True
    try:
        c.denoiser = 'OPENIMAGEDENOISE'
    except Exception:
        pass
    c.max_bounces = 3
    c.diffuse_bounces = 1
    c.glossy_bounces = 1
    c.transmission_bounces = 2
    c.transparent_max_bounces = 6
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.sample_clamp_indirect = 3.0
    scn.view_settings.view_transform = 'Standard'
    scn.view_settings.look = 'None'
    init_materials()
    return scn


def world_gradient(horizon, zenith, strength=1.0):
    scn = bpy.context.scene
    w = bpy.data.worlds.new("W")
    scn.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    bg.inputs["Strength"].default_value = strength
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sp = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(tc.outputs["Generated"], sp.inputs["Vector"])
    nt.links.new(sp.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = horizon
    ramp.color_ramp.elements[1].position = 0.65
    ramp.color_ramp.elements[1].color = zenith
    return w


def add_sun(energy, rot, color=(1.0, 1.0, 1.0)):
    ld = bpy.data.lights.new("sun", 'SUN')
    ld.energy = energy
    ld.angle = math.radians(4.0)
    ld.color = color
    ob = link(bpy.data.objects.new("sun", ld))
    ob.rotation_euler = rot
    return ob


def add_camera(lens=26.0):
    cd = bpy.data.cameras.new("cam")
    cd.lens = lens
    cd.clip_start = 0.05
    cd.clip_end = 600.0
    ob = link(bpy.data.objects.new("cam", cd))
    bpy.context.scene.camera = ob
    return ob


def add_fog(color, start, depth):
    """Névoa de profundidade via passe Mist + compositor (barata e estável no Cycles)."""
    scn = bpy.context.scene
    scn.world.mist_settings.start = start
    scn.world.mist_settings.depth = depth
    scn.world.mist_settings.falloff = 'QUADRATIC'
    scn.view_layers[0].use_pass_mist = True
    scn.use_nodes = True
    nt = scn.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new('CompositorNodeRLayers')
    rgb = nt.nodes.new('CompositorNodeRGB')
    mix = nt.nodes.new('CompositorNodeMixRGB')
    cmp_ = nt.nodes.new('CompositorNodeComposite')
    rgb.outputs[0].default_value = color
    mix.blend_type = 'MIX'
    nt.links.new(rl.outputs['Mist'], mix.inputs[0])
    nt.links.new(rl.outputs['Image'], mix.inputs[1])
    nt.links.new(rgb.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], cmp_.inputs['Image'])


def track_cam(cam, c, d, h, a=0.0, tgt=(0.0, 0.0, 0.0)):
    """Câmera lateral que segue o ponto c. a>0 gira para a frente do bicho."""
    pos = Vector((c.x + d * math.sin(a), c.y - d * math.cos(a), c.z + h))
    cam.location = pos
    look = Vector((c.x + tgt[0], c.y + tgt[1], c.z + tgt[2]))
    cam.rotation_euler = (look - pos).to_track_quat('-Z', 'Y').to_euler()


# ============================================================ cenário
def snow(count, box, size, seed=5, color_mat=None):
    rnd = random.Random(seed)
    me = blob_me("snow", 1.0, cf_flat(lin("#ffffff")), n=4, rings=2, mat=color_mat or MAT["emit"])
    (x0, x1, y0, y1, z0, z1) = box
    for i in range(count):
        s = size * rnd.uniform(0.5, 1.5)
        mesh_obj("snow", me, loc=(rnd.uniform(x0, x1), rnd.uniform(y0, y1), rnd.uniform(z0, z1)),
                 scale=(s, s, s))


def kelp(x, y, z, h, rnd):
    secs = []
    steps = 6
    for k in range(steps + 1):
        a = h * k / steps
        sway = 0.25 * h * 0.2 * math.sin(k * 0.9 + x)
        r = max(0.02, 0.10 * (1.0 - k / float(steps)) + 0.02)
        secs.append((a, sway, 0.0, r * 1.6, r * 0.6))
    col = mixc(lin("#2f8f4a"), lin("#7bd36a"), rnd.random())
    me = loft_me("kelp", secs, n=4, axis="Z", cfn=cf_flat(col, 0.1), mat=MAT["vc"], caps=(True, False),
                 seed=int(abs(x * 7 + y)) % 1000)
    return mesh_obj("kelp", me, loc=(x, y, z), rot=(0.0, 0.0, rnd.uniform(0, 3.14)))


def rock(x, y, z, r, rnd, base="#8a8f99"):
    me = blob_me("rock", r, cf_flat(lin(base), 0.12), n=6, rings=3, jit=r * 0.22,
                 seed=int(abs(x * 13 + y * 7)) % 1000 + 1, squash=0.8)
    return mesh_obj("rock", me, loc=(x, y, z), rot=(0.0, 0.0, rnd.uniform(0, 3.14)))


def env_underwater(x0, x1, floor_z, horizon, zenith, fog, fog_start, fog_depth, sun_energy,
                   floor_cols, seed=2, kelp_n=0, rock_n=0, snow_n=140, sun_col=(0.85, 0.95, 1.0)):
    rnd = random.Random(seed)
    world_gradient(horizon, zenith, 0.9)
    add_sun(sun_energy, (math.radians(30), math.radians(12), math.radians(-25)), sun_col)

    def hfn(x, y):
        return floor_z + 2.2 * noise2(x, y, 0.05, seed) + 0.6 * noise2(x, y, 0.18, seed + 3)

    lo, hi = floor_cols

    def cfn(c, nv, rr):
        base = mixc(lo, hi, clamp01(0.5 + 0.5 * noise2(c.x, c.y, 0.09, 4)))
        return scale_c(base, 1.0 + rr.uniform(-0.06, 0.06))

    terrain("floor", x0 - 80, x1 + 120, -90, 90, 6.0, hfn, cfn, MAT["vc"], seed=seed)
    for i in range(kelp_n):
        x = rnd.uniform(x0, x1 + 40)
        y = rnd.uniform(6, 30)
        safe(kelp, x, y, hfn(x, y) - 0.3, rnd.uniform(5, 11), rnd)
    for i in range(rock_n):
        x = rnd.uniform(x0, x1 + 40)
        y = rnd.uniform(5, 38)
        safe(rock, x, y, hfn(x, y) + 0.4, rnd.uniform(1.0, 2.8), rnd, "#6d7f86")
    safe(snow, snow_n, (x0 - 10, x1 + 50, -35, 40, floor_z + 3, 18), 0.07)
    safe(add_fog, fog, fog_start, fog_depth)
    return hfn


def tree_round(x, y, z, h, rnd, leaf="#4fb23f"):
    trunk = loft_me("trunk", [(0, 0, 0, 0.07 * h, 0.07 * h), (0.6 * h, 0, 0, 0.045 * h, 0.045 * h)],
                    n=5, axis="Z", cfn=cf_flat(lin("#6b4a2f")), mat=MAT["vc"], caps=(False, True))
    mesh_obj("trunk", trunk, loc=(x, y, z))
    R = 0.34 * h
    secs = [(0.40 * h, 0, 0, 0.01, 0.01), (0.52 * h, 0, 0, 0.8 * R, 0.8 * R), (0.70 * h, 0, 0, R, R),
            (0.88 * h, 0, 0, 0.72 * R, 0.72 * R), (1.0 * h, 0, 0, 0.01, 0.01)]
    col = mixc(lin(leaf), lin("#2f8a34"), rnd.random() * 0.6)
    me = loft_me("leaf", secs, n=7, axis="Z", cfn=cf_flat(col, 0.1), mat=MAT["vc"], jit=0.09 * R,
                 seed=int(abs(x * 11 + y)) % 997 + 1)
    mesh_obj("leaf", me, loc=(x, y, z))


def tree_acacia(x, y, z, h, rnd):
    trunk = loft_me("trunk", [(0, 0, 0, 0.08 * h, 0.08 * h), (0.8 * h, 0.05 * h, 0, 0.04 * h, 0.04 * h)],
                    n=5, axis="Z", cfn=cf_flat(lin("#5b4028")), mat=MAT["vc"], caps=(False, True))
    mesh_obj("trunk", trunk, loc=(x, y, z))
    R = 0.55 * h
    secs = [(0.78 * h, 0.05 * h, 0, 0.1 * R, 0.1 * R), (0.84 * h, 0.05 * h, 0, R, R),
            (0.93 * h, 0.05 * h, 0, 0.9 * R, 0.9 * R), (0.98 * h, 0.05 * h, 0, 0.4 * R, 0.4 * R)]
    col = mixc(lin("#5fae3a"), lin("#3f8f33"), rnd.random())
    me = loft_me("canopy", secs, n=8, axis="Z", cfn=cf_flat(col, 0.1), mat=MAT["vc"], jit=0.05 * R,
                 seed=int(abs(x * 5 + y * 3)) % 997 + 1)
    mesh_obj("canopy", me, loc=(x, y, z))


def mesa(x, y, z, R, H, rnd):
    def cf(c, nv, rr):
        k = int(c.z / (H / 5.0)) % 2
        base = lin("#d9702f") if k == 0 else lin("#ea8c48")
        return scale_c(base, 1.0 + rr.uniform(-0.05, 0.05))
    secs = [(0, 0, 0, R, R), (0.55 * H, 0, 0, 0.86 * R, 0.86 * R), (H, 0, 0, 0.7 * R, 0.7 * R)]
    me = loft_me("mesa", secs, n=8, axis="Z", cfn=cf, mat=MAT["vc"], jit=0.1 * R,
                 seed=int(abs(x + y * 3)) % 991 + 1)
    mesh_obj("mesa", me, loc=(x, y, z))


def cloud(x, y, z, s, rnd):
    for k in range(4):
        r = s * rnd.uniform(0.6, 1.0)
        me = blob_me("cl", r, cf_flat(lin("#ffffff"), 0.03), n=7, rings=4, jit=r * 0.1, seed=k + 3)
        mesh_obj("cl", me, loc=(x + k * s * 0.9, y + rnd.uniform(-1, 1), z + rnd.uniform(-0.3, 0.3) * s))


def reeds(x, y, z, rnd, n=7):
    for k in range(n):
        h = rnd.uniform(0.8, 1.6)
        me = cone_me("reed", 0.05, h, n=4, cfn=cf_flat(mixc(lin("#7a9a3a"), lin("#a9b24a"), rnd.random()), 0.08))
        mesh_obj("reed", me, loc=(x + rnd.uniform(-0.5, 0.5), y + rnd.uniform(-0.4, 0.4), z),
                 rot=(rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2), 0.0))


# ============================================================ criaturas
def chain_attach(bounds, a):
    """Em qual segmento da cadeia (bounds decrescente) fica a posição a? Devolve (k, x_local)."""
    k = 0
    for i in range(len(bounds) - 1):
        if bounds[i] >= a >= bounds[i + 1]:
            k = i
            break
        k = i
    return k, a - bounds[k]


def build_chain(name, tab, bounds, parent, cfn, n=12, ds=0.05, overlap=0.015, loc=(0.0, 0.0, 0.0)):
    L = abs(tab[-1][0] - tab[0][0])
    segs = []
    for k in range(len(bounds) - 1):
        a0, a1 = bounds[k], bounds[k + 1]
        aa0 = a0 + (overlap * L if k > 0 else 0.0)
        m = max(3, int(abs(aa0 - a1) / (ds * L)) + 1)
        secs = sample_prof(tab, m, aa0, a1, a0)
        me = loft_me("%s%d" % (name, k), secs, n=n, axis="X", cfn=cfn, mat=MAT["vc"], seed=10 + k)
        if k == 0:
            pos = (loc[0] + a0, loc[1], loc[2])
        else:
            pos = (a0 - bounds[k - 1], 0.0, 0.0)
        segs.append(mesh_obj("%s%d" % (name, k), me, parent=(segs[-1] if segs else parent), loc=pos))
    return segs


def eye(parent, loc, r):
    me = blob_me("eye", r, cf_flat(lin("#0b0d12"), 0.0), n=6, rings=3)
    return mesh_obj("eye", me, parent=parent, loc=loc)


def make_cetacean(parent, L, ftab, sbounds, cfn, fluke_s, fluke_k, pec_s, pec_k, pec_pts, fluke_plane="XY",
                  teeth=None, dorsal=None, fin_th=0.006, eyes_s=0.11, eye_r=0.004, seed=1):
    """Corpo em cadeia (cabeça->cauda), cauda, nadadeiras, dentes, olhos. Cabeça aponta para +X."""
    tab = [(L * (0.5 - s), ry * L, rz * L, cz * L) for (s, ry, rz, cz) in reversed(ftab)]
    bounds = [L * (0.5 - s) for s in sbounds]
    segs = build_chain("body", tab, bounds, parent, cfn)
    ctr_y = [(r[0], r[1]) for r in tab]
    ctr_z = [(r[0], r[2]) for r in tab]
    out = {"segs": segs, "fins": [], "fluke": None, "L": L}

    # cauda (nadadeira caudal)
    a = L * (0.5 - fluke_s)
    k, lx = chain_attach(bounds, a)
    base = fluke_k * L
    if fluke_plane == "XY":    # baleias: lobos horizontais
        pts = [(x * base, y * base) for (x, y) in FLUKE_WHALE]
        w = taper_w(pts, 0.14 * base)
        me = slab_me("fluke", pts, fin_th * L, "XY", w, cfn=cfn, mat=MAT["vc"], seed=seed)
    else:                      # tubarão: lobos verticais
        pts = [(x * base, y * base) for (x, y) in FLUKE_SHARK]
        w = taper_w(pts, 0.16 * base)
        me = slab_me("tail", pts, fin_th * L, "XZ", w, cfn=cfn, mat=MAT["vc"], seed=seed)
    out["fluke"] = mesh_obj("fluke", me, parent=segs[k], loc=(lx, 0.0, 0.0))

    # peitorais
    a = L * (0.5 - pec_s)
    k, lx = chain_attach(bounds, a)
    ry = curve(ctr_y, a)
    rz = curve(ctr_z, a)
    for sgn in (1.0, -1.0):
        pts = [(x * pec_k * L, sgn * y * pec_k * L) for (x, y) in pec_pts]
        w = taper_w(pts, 0.13 * pec_k * L)
        me = slab_me("pec", pts, fin_th * L * 0.8, "XY", w, cfn=cfn, mat=MAT["vc"], seed=seed + 1)
        rot = (-sgn * 0.55, 0.0, sgn * 0.12)
        ob = mesh_obj("pec", me, parent=segs[k], loc=(lx, sgn * ry * 0.95, -rz * 0.45), rot=rot)
        out["fins"].append((ob, rot, sgn))

    # dorsal
    if dorsal is not None:
        d_s, d_k, d_pts = dorsal
        a = L * (0.5 - d_s)
        k, lx = chain_attach(bounds, a)
        top = curve(ctr_z, a)
        pts = [(x * d_k * L, z * d_k * L) for (x, z) in d_pts]
        w = taper_w(pts, 0.14 * d_k * L)
        me = slab_me("dorsal", pts, fin_th * L * 0.9, "XZ", w, cfn=cfn, mat=MAT["vc"], seed=seed + 2)
        mesh_obj("dorsal", me, parent=segs[k], loc=(lx, 0.0, top * 0.92))

    # dentes na cabeça
    if teeth is not None:
        cnt, s0, s1, size, zfrac, sign = teeth
        tooth = cone_me("tooth", size, size * 2.4, n=4, sign=sign, seed=seed)
        for i in range(cnt):
            s = s0 + (s1 - s0) * i / max(1, cnt - 1)
            a = L * (0.5 - s)
            ry = curve(ctr_y, a)
            rz = curve(ctr_z, a)
            for sgn in (1.0, -1.0):
                mesh_obj("tooth", tooth, parent=segs[0], loc=(a - bounds[0], sgn * ry * 0.82, -rz * zfrac))

    # olhos
    a = L * (0.5 - eyes_s)
    ry = curve(ctr_y, a)
    rz = curve(ctr_z, a)
    for sgn in (1.0, -1.0):
        eye(segs[0], (a - bounds[0], sgn * ry * 0.93, rz * 0.1), max(eye_r * L, 0.03))
    return out


def anim_cetacean(c, t, freq, amps, lag, axis):
    w = 2.0 * math.pi * freq
    for k, seg in enumerate(c["segs"]):
        amp = amps[min(k, len(amps) - 1)]
        r = [0.0, 0.0, 0.0]
        r[axis] = amp * math.sin(w * t - lag * k)
        seg.rotation_euler = tuple(r)
    r = [0.0, 0.0, 0.0]
    r[axis] = amps[-1] * 0.9 * math.sin(w * t - lag * len(c["segs"]))
    c["fluke"].rotation_euler = tuple(r)
    for (ob, rot, sgn) in c["fins"]:
        ob.rotation_euler = (rot[0] + sgn * 0.12 * math.sin(w * t * 0.7), rot[1], rot[2])


FLUKE_WHALE = [(0.015, 0.0), (0.0, 0.035), (-0.035, 0.085), (-0.075, 0.125), (-0.06, 0.07),
               (-0.05, 0.02), (-0.045, 0.0), (-0.05, -0.02), (-0.06, -0.07), (-0.075, -0.125),
               (-0.035, -0.085), (0.0, -0.035)]
FLUKE_SHARK = [(0.012, 0.0), (-0.015, 0.06), (-0.05, 0.14), (-0.075, 0.15), (-0.06, 0.07),
               (-0.045, 0.0), (-0.06, -0.06), (-0.085, -0.10), (-0.05, -0.09), (-0.015, -0.04)]
PEC_WHALE = [(0.012, 0.0), (-0.004, 0.012), (-0.05, 0.095), (-0.075, 0.125), (-0.06, 0.05), (-0.035, 0.0)]
PEC_SHARK = [(0.02, 0.0), (-0.02, 0.03), (-0.07, 0.11), (-0.085, 0.12), (-0.06, 0.04), (-0.04, 0.0)]
DORSAL_SHARK = [(0.03, 0.0), (-0.01, 0.10), (-0.045, 0.16), (-0.065, 0.10), (-0.085, 0.0)]


def make_blue_whale(parent, L):
    back, mid, belly = lin("#456f98"), lin("#6e9bc0"), lin("#d8e4e8")

    def cf(c, nv, rnd):
        t = smooth(-0.45, 0.05, nv.z)
        col = mixc(belly, mixc(back, mid, rnd.random()), t)
        if nv.z < -0.3:
            stripe = int(math.floor(math.atan2(c.z, c.y) * 10.0 / math.pi)) % 2
            col = scale_c(col, 0.92 if stripe else 1.05)
        return scale_c(col, 1.0 + rnd.uniform(-0.08, 0.08))
    ftab = [(0.000, 0.004, 0.004, 0.0), (0.020, 0.035, 0.022, -0.002), (0.060, 0.058, 0.040, 0.0),
            (0.120, 0.072, 0.058, 0.002), (0.220, 0.080, 0.074, 0.004), (0.360, 0.083, 0.082, 0.004),
            (0.520, 0.072, 0.074, 0.003), (0.680, 0.048, 0.054, 0.002), (0.800, 0.028, 0.034, 0.001),
            (0.900, 0.014, 0.022, 0.0), (0.960, 0.009, 0.016, 0.0), (1.000, 0.006, 0.010, 0.0)]
    return make_cetacean(parent, L, ftab, [0.0, 0.50, 0.68, 0.82, 1.0], cf, 0.955, 1.0, 0.21, 1.0,
                         PEC_WHALE, dorsal=(0.72, 0.9, [(0.02, 0.0), (-0.012, 0.035), (-0.045, 0.0)]),
                         eye_r=0.0045, seed=4)


def make_basilosaurus(parent, L):
    cf = cf_animal(lin("#5d6e75"), lin("#cfd3c3"))
    ftab = [(0.000, 0.004, 0.004, 0.0), (0.020, 0.014, 0.010, -0.001), (0.060, 0.018, 0.014, 0.0),
            (0.100, 0.030, 0.028, 0.002), (0.160, 0.034, 0.034, 0.002), (0.300, 0.037, 0.037, 0.002),
            (0.480, 0.037, 0.037, 0.002), (0.650, 0.030, 0.031, 0.001), (0.800, 0.020, 0.022, 0.0),
            (0.900, 0.011, 0.013, 0.0), (0.960, 0.007, 0.009, 0.0), (1.000, 0.005, 0.006, 0.0)]
    return make_cetacean(parent, L, ftab, [0.0, 0.18, 0.34, 0.50, 0.64, 0.78, 0.90, 1.0], cf,
                         0.965, 0.55, 0.17, 0.5, PEC_WHALE, teeth=(7, 0.02, 0.095, 0.012, 0.35, -1.0),
                         fin_th=0.004, eyes_s=0.105, eye_r=0.0045, seed=6)


def make_aetiocetus(parent, L):
    cf = cf_animal(lin("#6f8070"), lin("#dcd8c0"))
    ftab = [(0.000, 0.006, 0.006, 0.0), (0.030, 0.030, 0.024, -0.004), (0.080, 0.050, 0.040, -0.002),
            (0.160, 0.075, 0.068, 0.004), (0.300, 0.092, 0.088, 0.006), (0.480, 0.085, 0.082, 0.004),
            (0.650, 0.060, 0.062, 0.002), (0.800, 0.036, 0.040, 0.0), (0.920, 0.020, 0.028, 0.0),
            (1.000, 0.012, 0.018, 0.0)]
    return make_cetacean(parent, L, ftab, [0.0, 0.35, 0.62, 0.82, 1.0], cf, 0.955, 0.7, 0.28, 0.7,
                         PEC_WHALE, teeth=(6, 0.03, 0.10, 0.02, 0.30, -1.0), fin_th=0.008,
                         eyes_s=0.10, eye_r=0.012, seed=8)


def make_megalodon(parent, L):
    cf = cf_animal(lin("#4a5560"), lin("#e8ebec"), belly_at=-0.1)
    ftab = [(0.000, 0.004, 0.004, 0.0), (0.030, 0.030, 0.028, 0.0), (0.080, 0.055, 0.055, 0.0),
            (0.180, 0.085, 0.090, 0.0), (0.340, 0.100, 0.110, 0.0), (0.550, 0.085, 0.090, 0.0),
            (0.720, 0.050, 0.055, 0.0), (0.850, 0.028, 0.030, 0.0), (0.930, 0.018, 0.020, 0.0),
            (1.000, 0.012, 0.012, 0.0)]
    return make_cetacean(parent, L, ftab, [0.0, 0.30, 0.52, 0.72, 0.88, 1.0], cf, 0.96, 1.0, 0.30, 1.0,
                         PEC_SHARK, fluke_plane="XZ", teeth=(9, 0.05, 0.15, 0.03, 0.88, -1.0),
                         dorsal=(0.40, 1.0, DORSAL_SHARK), fin_th=0.005, eyes_s=0.09, eye_r=0.004, seed=9)


def make_leg(parent, name, loc, up_len, lo_len, r0, r1, r2, foot, cfn, splay=0.0, seed=1):
    vc = MAT["vc"]
    up_secs = [(0, 0, 0, r0, r0 * 0.9), (-up_len * 0.5, 0, 0, r0 * 0.9, r0 * 0.85), (-up_len, 0, 0, r1, r1)]
    up = mesh_obj(name + "U", loft_me(name + "U", up_secs, n=6, axis="Z", cfn=cfn, mat=vc, seed=seed),
                  parent=parent, loc=loc, rot=(splay, 0.0, 0.0))
    lo_secs = [(0, 0, 0, r1, r1), (-lo_len, 0, 0, r2, r2)]
    lo = mesh_obj(name + "L", loft_me(name + "L", lo_secs, n=6, axis="Z", cfn=cfn, mat=vc, seed=seed + 1),
                  parent=up, loc=(0.0, 0.0, -up_len))
    ft_secs = [(-0.3 * foot, 0, 0.3 * r2, r2, r2 * 0.6), (0.0, 0, 0.3 * r2, r2 * 1.2, r2 * 0.7),
               (foot, 0, 0.1 * r2, r2 * 0.9, r2 * 0.45)]
    mesh_obj(name + "F", loft_me(name + "F", ft_secs, n=6, axis="X", cfn=cf_flat(lin("#3d3226")), mat=vc,
                                 seed=seed + 2), parent=lo, loc=(0.0, 0.0, -lo_len))
    return up, lo


def make_pakicetus(parent):
    cf = cf_animal(lin("#8f6d49"), lin("#dcc7a1"))
    cfd = cf_animal(lin("#51402e"), lin("#7b6448"))
    vc = MAT["vc"]
    tor = [(-0.46, 0.09, 0.11, 0.0), (-0.30, 0.14, 0.16, 0.0), (0.0, 0.17, 0.19, 0.01),
           (0.30, 0.17, 0.20, 0.015), (0.48, 0.12, 0.15, 0.01)]
    body = mesh_obj("pk_body", loft_me("pk_body", sample_prof(tor, 9, -0.46, 0.48, 0.0), n=10, axis="X",
                                       cfn=cf, mat=vc, seed=3), parent=parent, loc=(0.0, 0.0, 0.55))
    hd = [(0.0, 0.10, 0.12, 0.0), (0.12, 0.095, 0.115, 0.0), (0.24, 0.085, 0.09, -0.01),
          (0.34, 0.055, 0.055, -0.025), (0.52, 0.028, 0.026, -0.045)]
    head = mesh_obj("pk_head", loft_me("pk_head", sample_prof(hd, 8, 0.0, 0.52, 0.0), n=8, axis="X",
                                       cfn=cf, mat=vc, seed=4), parent=body, loc=(0.40, 0.0, 0.08))
    ear = cone_me("ear", 0.035, 0.09, n=4, cfn=cf_flat(lin("#6e5238")))
    for s in (1.0, -1.0):
        mesh_obj("ear", ear, parent=head, loc=(0.14, s * 0.06, 0.12))
        eye(head, (0.27, s * 0.072, 0.02), 0.018)
    mesh_obj("nose", blob_me("nose", 0.022, cf_flat(lin("#15110d"), 0.0), n=6, rings=3), parent=head,
             loc=(0.51, 0.0, -0.043))
    t1 = mesh_obj("pk_t1", loft_me("pk_t1", sample_prof([(-0.36, 0.03, 0.03, -0.02), (0.0, 0.06, 0.06, 0.0)],
                                                         5, 0.0, -0.36, 0.0), n=7, axis="X", cfn=cf, mat=vc,
                                   seed=5), parent=body, loc=(-0.44, 0.0, 0.0))
    t2 = mesh_obj("pk_t2", loft_me("pk_t2", sample_prof([(-0.32, 0.012, 0.012, -0.03), (0.0, 0.03, 0.03, 0.0)],
                                                         5, 0.0, -0.32, 0.0), n=6, axis="X", cfn=cf, mat=vc,
                                   seed=6), parent=t1, loc=(-0.36, 0.0, 0.0))
    legs = []
    for (x, y, ph, nm) in ((0.28, 0.10, 0.0, "fl"), (0.28, -0.10, math.pi, "fr"),
                           (-0.28, 0.10, math.pi, "hl"), (-0.28, -0.10, 0.0, "hr")):
        up, lo = make_leg(body, "pk_" + nm, (x, y, -0.09), 0.22, 0.24, 0.065, 0.045, 0.028, 0.10, cfd,
                          seed=20 + len(legs))
        legs.append((up, lo, ph))
    return {"root": parent, "body": body, "head": head, "tail": [t1, t2], "legs": legs}


def anim_pakicetus(c, t):
    w = 2.0 * math.pi * 1.25
    for (up, lo, ph) in c["legs"]:
        p = w * t + ph
        up.rotation_euler = (0.0, 0.55 * math.sin(p), 0.0)
        lo.rotation_euler = (0.0, 0.9 * max(0.0, -math.cos(p)) + 0.15, 0.0)
    c["body"].location = (0.0, 0.0, 0.55 + 0.015 * abs(math.sin(w * t)))
    c["head"].rotation_euler = (0.0, 0.07 * math.sin(2 * w * t) + 0.12, 0.0)
    for k, tl in enumerate(c["tail"]):
        tl.rotation_euler = (0.0, 0.1, 0.35 * math.sin(w * 0.5 * t - 0.8 * k))


def make_ambulocetus(parent):
    cf = cf_animal(lin("#6f6a4d"), lin("#c9bf93"))
    cfd = cf_animal(lin("#4d4a35"), lin("#6f6a4d"))
    vc = MAT["vc"]
    tor = [(-0.75, 0.20, 0.19, 0.0), (-0.40, 0.30, 0.27, 0.0), (0.0, 0.33, 0.30, 0.01),
           (0.40, 0.31, 0.28, 0.01), (0.75, 0.22, 0.21, 0.0)]
    body = mesh_obj("am_body", loft_me("am_body", sample_prof(tor, 10, -0.75, 0.75, 0.0), n=10, axis="X",
                                       cfn=cf, mat=vc, seed=3), parent=parent, loc=(0.0, 0.0, 0.40))
    hd = [(0.0, 0.20, 0.17, 0.0), (0.25, 0.17, 0.13, -0.01), (0.55, 0.10, 0.07, -0.02), (0.92, 0.055, 0.04, -0.03)]
    head = mesh_obj("am_head", loft_me("am_head", sample_prof(hd, 8, 0.0, 0.92, 0.0), n=8, axis="X", cfn=cf,
                                       mat=vc, seed=4), parent=body, loc=(0.72, 0.0, 0.03))
    tooth = cone_me("tooth", 0.02, 0.06, n=4, sign=-1.0)
    for i in range(6):
        x = 0.36 + 0.09 * i
        ry = curve([(r[0], r[1]) for r in hd], x)
        for s in (1.0, -1.0):
            mesh_obj("tooth", tooth, parent=head, loc=(x, s * ry * 0.85, -0.03))
    for s in (1.0, -1.0):
        eye(head, (0.30, s * 0.11, 0.115), 0.035)
    tails = []
    prev, prev_x = body, -0.75
    spec = [(0.50, 0.20, 0.14), (0.45, 0.14, 0.08), (0.40, 0.08, 0.03)]
    for k, (ln, r0, r1) in enumerate(spec):
        tb = [(-ln, r1, r1 * 0.9, 0.0), (0.0, r0, r0 * 0.9, 0.0)]
        ob = mesh_obj("am_t%d" % k, loft_me("am_t%d" % k, sample_prof(tb, 5, 0.0, -ln, 0.0), n=8, axis="X",
                                            cfn=cf, mat=vc, seed=30 + k), parent=prev,
                      loc=((-0.75 if k == 0 else -spec[k - 1][0]), 0.0, 0.0))
        tails.append(ob)
        prev = ob
    legs = []
    for (x, y, ph, nm, big) in ((0.50, 0.30, 0.0, "fl", 1.0), (0.50, -0.30, math.pi, "fr", 1.0),
                                (-0.45, 0.30, math.pi, "hl", 1.5), (-0.45, -0.30, 0.0, "hr", 1.5)):
        sgn = 1.0 if y > 0 else -1.0
        up, lo = make_leg(body, "am_" + nm, (x, y, -0.18), 0.16, 0.20, 0.09, 0.065, 0.05 * big, 0.30 * big, cfd,
                          splay=-sgn * 0.55, seed=40 + len(legs))
        legs.append((up, lo, ph, sgn))
    return {"root": parent, "body": body, "head": head, "tail": tails, "legs": legs}


def anim_ambulocetus(c, t):
    w = 2.0 * math.pi * 0.9
    for (up, lo, ph, sgn) in c["legs"]:
        p = w * t + ph
        up.rotation_euler = (-sgn * 0.55, 0.6 * math.sin(p), 0.0)
        lo.rotation_euler = (0.0, 0.7 * max(0.0, -math.cos(p)) + 0.2, 0.0)
    c["body"].location = (0.0, 0.0, 0.40 + 0.03 * math.sin(w * t * 0.5))
    c["head"].rotation_euler = (0.0, 0.05 * math.sin(w * t * 0.5) + 0.05, 0.0)
    for k, tl in enumerate(c["tail"]):
        tl.rotation_euler = (0.0, 0.22 * math.sin(w * t * 0.8 - 0.9 * k), 0.12 * math.sin(w * t * 0.4 - 0.6 * k))


# ============================================================ cenas (cada uma devolve upd(t, f))
def scene_whale(T, mode):
    L = 24.0
    cam = add_camera(26.0)
    env_underwater(-10, 2.4 * T + 40, -38, lin("#0d4f8f"), lin("#52c9ea"), lin("#0c4d86"), 6.0, 70.0,
                   4.0, (lin("#2c6d86"), lin("#4f9bac")), seed=2, kelp_n=0, rock_n=6, snow_n=160)
    root = empty("root")
    wh = make_blue_whale(root, L)
    speed = 2.0 if mode == "intro" else 2.3
    krill = None
    if mode == "final":
        krill = safe(make_krill, 170)

    def upd(t, f):
        x, z = speed * t, 0.5 * math.sin(0.35 * t)
        root.location = (x, 0.0, z)
        anim_cetacean(wh, t, 0.2, [0.012, 0.04, 0.09, 0.14], 0.9, 1)
        c = Vector((x, 0.0, z))
        if mode == "intro":
            a = 0.85 - 0.8 * smooth(0.0, max(T, 1.0), t)
            track_cam(cam, c, 24.0, 2.0, a, (0.0, 0.0, 0.0))
        else:
            track_cam(cam, c, 19.0, 1.2, -0.25 + 0.04 * t, (2.0, 0.0, 0.0))
        if krill is not None:
            krill.location = (x * 0.0, 0.0, 0.0)
    return upd


def make_krill(count):
    rnd = random.Random(9)
    mat = emit_material("krill", lin("#ff8f66"), 2.2)
    me = blob_me("kr", 1.0, cf_flat(lin("#ff8f66")), n=4, rings=2, mat=mat, squash=0.6)
    holder = empty("krill")
    for i in range(count):
        s = rnd.uniform(0.10, 0.2)
        mesh_obj("kr", me, parent=holder,
                 loc=(rnd.uniform(14, 46), rnd.uniform(-7, 7), rnd.uniform(-5, 6)), scale=(s * 2.0, s, s))
    return holder


def scene_pakicetus(T):
    speed = 1.15
    span = speed * T + 8
    rnd = random.Random(3)
    cam = add_camera(26.0)
    world_gradient(lin("#ffe1b0"), lin("#79b9ea"), 1.0)
    add_sun(4.2, (math.radians(48), math.radians(8), math.radians(-35)), (1.0, 0.93, 0.82))

    def hfn(x, y):
        a = smooth(3.0, 11.0, abs(y))
        h = 0.9 * a * noise2(x, y, 0.12)
        if 3.2 < y < 7.4:
            h -= 0.55 * math.sin(math.pi * (y - 3.2) / 4.2)
        h += smooth(12.0, 48.0, y) * (6.0 + 6.0 * abs(noise2(x, y, 0.05, 2.0)))
        return h

    def cfn(c, nv, rr):
        if c.y > 16:
            base = mixc(lin("#c85f2c"), lin("#eb8f4d"), smooth(0, 12, c.z))
        elif nv.z < 0.82:
            base = lin("#c97b3a")
        else:
            base = mixc(lin("#e6d15e"), lin("#d8b845"), rr.random())
        return scale_c(base, 1.0 + rr.uniform(-0.06, 0.06))
    terrain("land", -30, span + 55, -12, 75, 1.7, hfn, cfn, MAT["vc"], seed=4)
    water = terrain("river", -30, span + 55, 3.4, 7.2, 3.0, lambda x, y: -0.16,
                    lambda c, nv, rr: lin("#3a9fe0", 0.7), water_material("river", lin("#2f9bdc"), 0.78), seed=1)
    for i in range(16):
        x, y = rnd.uniform(-12, span + 30), rnd.uniform(9, 30)
        safe(tree_acacia, x, y, hfn(x, y), rnd.uniform(4, 6.5), rnd)
    for i in range(10):
        x, y = rnd.uniform(-12, span + 30), rnd.uniform(9, 24)
        safe(tree_round, x, y, hfn(x, y), rnd.uniform(2.5, 4.0), rnd, "#79b43f")
    for i in range(7):
        safe(mesa, rnd.uniform(-20, span + 40), rnd.uniform(34, 52), 0.0, rnd.uniform(6, 11), rnd.uniform(8, 14), rnd)
    for i in range(10):
        x, y = rnd.uniform(-8, span + 20), rnd.uniform(1.4, 2.6)
        safe(rock, x, y, hfn(x, y) + 0.05, rnd.uniform(0.15, 0.4), rnd, "#a06a3c")
    for i in range(4):
        safe(cloud, rnd.uniform(-30, span + 30), rnd.uniform(55, 85), rnd.uniform(20, 32), rnd.uniform(5, 8), rnd)
    safe(add_fog, lin("#f6d9ae"), 10.0, 90.0)
    root = empty("root")
    pk = make_pakicetus(root)

    def upd(t, f):
        x = speed * t
        root.location = (x, 0.0, 0.0)
        anim_pakicetus(pk, t)
        track_cam(cam, Vector((x, 0.0, 0.45)), 3.2, 0.15, 0.25 * math.sin(0.5 * t), (0.1, 0.0, 0.0))
    return upd


def scene_ambulocetus(T):
    speed = 1.3
    span = speed * T + 8
    rnd = random.Random(5)
    cam = add_camera(26.0)
    world_gradient(lin("#ffd9a8"), lin("#6fb4e6"), 1.0)
    add_sun(3.8, (math.radians(52), math.radians(6), math.radians(-30)), (1.0, 0.92, 0.80))

    def hfn(x, y):
        h = -1.1 + 0.25 * noise2(x, y, 0.2)
        h += smooth(5.0, 12.0, y) * 2.2
        h += smooth(14.0, 50.0, y) * (7.0 + 5.0 * abs(noise2(x, y, 0.05, 1.0)))
        h += smooth(-9.0, -4.0, -y) * 1.6
        return h

    def cfn(c, nv, rr):
        if c.z > 5:
            base = mixc(lin("#3d9a3c"), lin("#68b74a"), rr.random())
        elif c.z > 0.2:
            base = mixc(lin("#7f8a3d"), lin("#a89a55"), rr.random())
        else:
            base = mixc(lin("#8a7348"), lin("#b09a63"), rr.random())
        return scale_c(base, 1.0 + rr.uniform(-0.06, 0.06))
    terrain("land", -30, span + 55, -20, 80, 1.8, hfn, cfn, MAT["vc"], seed=6)
    terrain("water", -30, span + 55, -20, 14, 6.0, lambda x, y: 0.30, lambda c, nv, rr: lin("#2fb5b0", 0.5),
            water_material("water", lin("#2fb5b0"), 0.55, 0.08), seed=2)
    for i in range(10):
        x, y = rnd.uniform(-12, span + 30), rnd.uniform(7.0, 9.5)
        safe(reeds, x, y, hfn(x, y), rnd)
    for i in range(12):
        x, y = rnd.uniform(-12, span + 30), rnd.uniform(14, 36)
        safe(tree_round, x, y, hfn(x, y), rnd.uniform(3.0, 5.5), rnd, "#58a83f")
    for i in range(5):
        safe(cloud, rnd.uniform(-30, span + 30), rnd.uniform(55, 85), rnd.uniform(22, 34), rnd.uniform(5, 8), rnd)
    safe(snow, 60, (-10, span + 30, -5, 8, -0.8, 1.4), 0.025)
    safe(add_fog, lin("#e9d9b4"), 10.0, 80.0)
    root = empty("root")
    am = make_ambulocetus(root)

    def upd(t, f):
        x = speed * t
        root.location = (x, 0.0, 0.0)
        anim_ambulocetus(am, t)
        track_cam(cam, Vector((x, 0.0, 0.35)), 6.0, 0.55, 0.22 * math.sin(0.45 * t), (0.2, 0.0, 0.0))
    return upd


def scene_basilosaurus(T):
    L = 15.0
    cam = add_camera(26.0)
    env_underwater(-10, 3.0 * T + 40, -34, lin("#0f5c9a"), lin("#5ed0ea"), lin("#0e5aa0"), 5.0, 62.0,
                   4.2, (lin("#2f7f8c"), lin("#59b0b0")), seed=7, kelp_n=0, rock_n=8, snow_n=170)
    root = empty("root")
    bs = make_basilosaurus(root, L)

    def upd(t, f):
        x, z = 3.0 * t, 0.6 * math.sin(0.5 * t)
        root.location = (x, 0.0, z)
        anim_cetacean(bs, t, 0.55, [0.03, 0.06, 0.10, 0.14, 0.18, 0.22, 0.26], 0.55, 1)
        track_cam(cam, Vector((x, 0.0, z)), 16.0, 1.5, 0.20 * math.sin(0.4 * t) - 0.1, (0.0, 0.0, 0.0))
    return upd


def scene_aetiocetus(T):
    L = 3.6
    cam = add_camera(26.0)
    env_underwater(-10, 1.9 * T + 40, -6.5, lin("#15869f"), lin("#7fe6e0"), lin("#12809b"), 3.0, 36.0,
                   4.5, (lin("#caa86a"), lin("#e3cd8e")), seed=11, kelp_n=26, rock_n=14, snow_n=150,
                   sun_col=(1.0, 0.98, 0.9))
    root = empty("root")
    ae = make_aetiocetus(root, L)

    def upd(t, f):
        x, z = 1.9 * t, 0.25 * math.sin(0.8 * t)
        root.location = (x, 0.0, z)
        anim_cetacean(ae, t, 0.9, [0.03, 0.08, 0.14, 0.2], 0.8, 1)
        track_cam(cam, Vector((x, 0.0, z)), 4.9, 0.5, 0.18 * math.sin(0.5 * t), (0.1, 0.0, 0.0))
    return upd


def scene_mega(T):
    cam = add_camera(26.0)
    env_underwater(-30, 3.2 * T + 60, -40, lin("#26121c"), lin("#1a5a86"), lin("#1d2a44"), 8.0, 55.0,
                   2.2, (lin("#2a3a4a"), lin("#3d5566")), seed=13, rock_n=4, snow_n=140,
                   sun_col=(0.8, 0.85, 1.0))
    rw = empty("whale_root")
    wh = make_blue_whale(rw, 20.0)
    rm = empty("mega_root")
    mg = make_megalodon(rm, 16.0)

    def upd(t, f):
        xw = 3.0 * t
        rw.location = (xw, 4.0, 0.4 * math.sin(0.5 * t))
        anim_cetacean(wh, t, 0.22, [0.012, 0.04, 0.09, 0.14], 0.9, 1)
        xm = -26.0 + 5.4 * t
        rm.location = (xm, 17.0 - 1.2 * t, 1.5 + 0.3 * math.sin(0.7 * t))
        rm.rotation_euler = (0.0, 0.0, 0.0)
        anim_cetacean(mg, t, 0.7, [0.03, 0.07, 0.12, 0.17, 0.22], 0.7, 2)
        c = Vector((xw * 0.55 + 6.0, 0.0, 1.0))
        track_cam(cam, c, 26.0, 1.5, 0.05 * math.sin(0.3 * t), (0.0, 8.0, 0.0))
    return upd


BUILDERS = {
    "whale_intro": lambda T: scene_whale(T, "intro"),
    "pakicetus": scene_pakicetus,
    "ambulocetus": scene_ambulocetus,
    "basilosaurus": scene_basilosaurus,
    "aetiocetus": scene_aetiocetus,
    "blue_whale": lambda T: scene_whale(T, "final"),
    "megalodon": scene_mega,
}


# ============================================================ main
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--timeline", default="")
    p.add_argument("--scene", type=int, default=0)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=1)
    p.add_argument("--out", default="frames")
    p.add_argument("--width", type=int, default=720)
    p.add_argument("--height", type=int, default=1280)
    p.add_argument("--samples", type=int, default=32)
    p.add_argument("--smoke", action="store_true")
    return p.parse_args(argv)


def render_scene(si, model, nframes, f_start, f_end, out, W, H, samples):
    scn = reset_scene(W, H, samples)
    T = nframes / float(FPS) + 1.0
    upd = BUILDERS[model](T)
    os.makedirs(out, exist_ok=True)
    for f in range(f_start, f_end):
        upd(f / float(FPS), f)
        scn.render.filepath = os.path.abspath(os.path.join(out, "f%d_%05d" % (si, f)))
        bpy.ops.render.render(write_still=True)
        print("OK frame cena %d  %d/%d" % (si, f + 1 - f_start, f_end - f_start))


def main():
    a = parse_args()
    if a.smoke:
        # teste de ambiente: 1 frame minúsculo de cada cena
        models = ["whale_intro", "pakicetus", "ambulocetus", "basilosaurus", "aetiocetus", "blue_whale", "megalodon"]
        for si, m in enumerate(models):
            render_scene(si, m, 150, 45, 46, a.out, 180, 320, 4)
        print("SMOKE OK")
        return
    with open(a.timeline, "r", encoding="utf-8") as fh:
        tl = json.load(fh)
    sc = tl["scenes"][a.scene]
    render_scene(a.scene, sc["model"], sc["nframes"], a.start, a.end, a.out, a.width, a.height, a.samples)


main()
