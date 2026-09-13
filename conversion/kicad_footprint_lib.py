#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#Identify equal footprints and assign KiCad library names
#Two components share a footprint when silkscreen objects are equal
#and pads have equal sizes and distances
#Author: cdhigh <https://github.com/cdhigh>, clemarfolly <https://github.com/clemarfolly>
import math
from sprint_struct.sprint_element import LAYER_S1, LAYER_S2
from sprint_struct.sprint_track import SprintTrack
from sprint_struct.sprint_pad import SprintPad
from sprint_struct.sprint_polygon import SprintPolygon
from sprint_struct.sprint_text import SprintText
from sprint_struct.sprint_circle import SprintCircle
from sprint_struct.sprint_group import SprintGroup
from sprint_struct.sprint_component import SprintComponent

SILK_LAYERS = (LAYER_S1, LAYER_S2)

#Round float to 2 decimals, robust against None/invalid values
def r2(value):
    try:
        return round(float(value), 2)
    except:
        return 0

#Depth-first pads of a component in document order, going through groups
#Pads inside nested components are skipped (rendered as separate footprints)
def iterFootprintPads(comp):
    pads = []
    def visit(elems):
        for elem in elems:
            if isinstance(elem, SprintPad):
                pads.append(elem)
            elif isinstance(elem, SprintGroup):
                visit(elem.elements)
    visit(comp.elements)
    return pads

#Euclidean distance between two pads (translation invariant)
def padDistance(pad1, pad2):
    return math.dist(pad1.pos, pad2.pos)

#Largest distance between any two pads of the list
def maxPadDistance(pads):
    best = 0
    for i in range(len(pads)):
        for j in range(i + 1, len(pads)):
            best = max(best, padDistance(pads[i], pads[j]))
    return best

#Format a distance for a footprint name, 5.08 -> '5.08', 10.0 -> '10'
def formatDistance(dist):
    text = f"{r2(dist):.2f}"
    return text.rstrip('0').rstrip('.') if '.' in text else text

#Cluster 1D values with tolerance, return sorted cluster means
def clusterValues(vals, tol=0.05):
    groups = []
    for v in sorted(vals):
        if groups and abs(v - groups[-1][-1]) <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return sorted([sum(g) / len(g) for g in groups])

#Distance between the two pin rows of a DIP-like component
#Rows are the two clusters on the axis showing exactly two groups,
#fallback is the largest board span when no clear two-row layout exists
def pinRowDistance(pads):
    xs = clusterValues([p.pos[0] for p in pads])
    if len(xs) == 2:
        return abs(xs[1] - xs[0])
    ys = clusterValues([p.pos[1] for p in pads])
    if len(ys) == 2:
        return abs(ys[1] - ys[0])
    xSpan = max([p.pos[0] for p in pads]) - min([p.pos[0] for p in pads])
    ySpan = max([p.pos[1] for p in pads]) - min([p.pos[1] for p in pads])
    return max(xSpan, ySpan)

#True when the component has a closed circle on a silkscreen layer
def hasClosedSilkCircle(comp):
    for elem in comp.baseDrawElements():
        if (isinstance(elem, SprintCircle) and elem.layerIdx in SILK_LAYERS
                and elem.start == elem.stop and elem.radius > 0):
            return True
    return False

#Serialize one silkscreen element, coordinates relative to origin ox/oy
def serializeSilkElem(elem, ox, oy):
    if isinstance(elem, SprintTrack):
        pts = [(r2(p[0] - ox), r2(p[1] - oy)) for p in elem.points]
        return ('TRK', r2(elem.width), tuple(pts))
    if isinstance(elem, SprintCircle):
        return ('CIR', r2(elem.center[0] - ox), r2(elem.center[1] - oy),
            r2(elem.radius), r2(elem.start), r2(elem.stop), r2(elem.width),
            bool(elem.fill))
    if isinstance(elem, SprintPolygon):
        pts = [(r2(p[0] - ox), r2(p[1] - oy)) for p in elem.points]
        return ('POL', r2(elem.width), tuple(pts))
    if isinstance(elem, SprintText):
        return ('TXT', r2(elem.pos[0] - ox), r2(elem.pos[1] - oy),
            r2(elem.height), elem.rotation, bool(elem.mirrorH),
            bool(elem.mirrorV), elem.text)
    return None

#Canonical footprint signature: silkscreen geometry plus pad sizes and
#relative positions, all coordinates relative to the component bbox origin
#so equal footprints at different board locations share the signature.
#ID/VALUE texts are excluded because references always differ per instance.
def footprintSignature(comp):
    comp.updateSelfBbox()
    ox, oy = comp.xMin, comp.yMin
    pads = iterFootprintPads(comp)
    padKeys = []
    for pad in pads:
        padKeys.append(('PAD', pad.padType, r2(pad.sizeX), r2(pad.sizeY),
            r2(pad.drill), pad.form, pad.rotation % 360, pad.layerIdx,
            bool(pad.via), r2(pad.pos[0] - ox), r2(pad.pos[1] - oy)))
    padKeys.sort()
    silkKeys = []
    for elem in comp.baseDrawElements():
        if elem is comp.idText or elem is comp.valueText:
            continue
        if elem.layerIdx not in SILK_LAYERS:
            continue
        key = serializeSilkElem(elem, ox, oy)
        if key is not None:
            silkKeys.append(key)
    silkKeys.sort(key=repr)
    return repr((tuple(padKeys), tuple(silkKeys)))

#Base library name by component rules, XXX is pad distance in mm,
#Conn uses pad count and DIP uses pin count plus row distance.
#Unmatched components fall back to X_<padCount>P.
def footprintBaseName(comp):
    compId = (comp.idText.text or '').strip().upper()
    prefix = compId[:1] if compId else ''
    pads = [e for e in comp.baseDrawElements() if isinstance(e, SprintPad)]
    padCount = len(pads)
    if padCount == 0:
        return 'X_0P'
    if prefix == 'R' and padCount == 2:
        return f"R_{formatDistance(padDistance(pads[0], pads[1]))}"
    if prefix == 'C' and padCount >= 2 and hasClosedSilkCircle(comp):
        dist = padDistance(pads[0], pads[1]) if padCount == 2 else maxPadDistance(pads)
        return f"CP_{formatDistance(dist)}"
    if prefix == 'C' and padCount == 2:
        return f"C_{formatDistance(padDistance(pads[0], pads[1]))}"
    if prefix == 'D' and padCount == 2:
        return f"D_{formatDistance(padDistance(pads[0], pads[1]))}"
    if prefix == 'J' and padCount >= 1:
        return f"Conn_{padCount}"
    if prefix == 'Q' and padCount == 3:
        return f"T_{formatDistance(maxPadDistance(pads))}"
    if prefix == 'U' and padCount >= 1:
        return f"DIP{padCount}_{formatDistance(pinRowDistance(pads))}"
    return f"X_{padCount}P"

#Assign one library name per component. Components with equal base name and
#equal signature reuse the same footprint, equal base name but different
#signature gets a new type suffix _T2, _T3, ...
#Returns (compIdToName, nameToRepComp)
def assignLibraryFootprints(components):
    compIdToName = {}
    nameToRepComp = {}
    baseTypes = {}
    for comp in components:
        base = footprintBaseName(comp)
        sig = footprintSignature(comp)
        types = baseTypes.setdefault(base, [])
        for prevSig, typeNo in types:
            if prevSig == sig:
                name = base if typeNo == 1 else f"{base}_T{typeNo}"
                break
        else:
            typeNo = len(types) + 1
            types.append((sig, typeNo))
            name = base if typeNo == 1 else f"{base}_T{typeNo}"
            nameToRepComp[name] = comp
        compIdToName[id(comp)] = name
    return compIdToName, nameToRepComp
