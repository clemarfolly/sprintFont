#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#Convert Sprint-Layout components to KiCad footprint files (.kicad_mod)
#Footprint format: https://dev-docs.kicad.org/en/file-formats/sexpr-intro/index.html#_footprint
#Author: cdhigh <https://github.com/cdhigh>, clemarfolly <https://github.com/clemarfolly>
import math
import uuid
from .kicad_definitions import *
from sprint_struct.sprint_textio import *

def uuid4():
    return str(uuid.uuid4())

#Keep decimal places while handling None or invalid values robustly (e.g. {var:.2f})
def r2(value):
    try:
        return round(value, 2)
    except:
        return 0

class KicadModGenerator:
    #comp: SprintComponent object
    #footprintName: footprint name, uses component comment or idText if empty
    #forLibrary: library mode, generic REF** reference and sequential pad numbers
    def __init__(self, comp, footprintName='', forLibrary=False):
        self.comp = comp
        self.footprintName = footprintName or comp.comment or comp.idText.text or 'Footprint'
        self.forLibrary = forLibrary
        self._padSeq = 0

    #Main interface to export KiCad footprint, returns error message on failure
    def generate(self, outputFile):
        try:
            centroid = self.comp.centroid()
            with open(outputFile, 'w', encoding='utf-8') as f:
                self.writeHeader(f, centroid)
                self.writeElements(f, centroid)
                self.writeFooter(f)
            return ''
        except Exception as e:
            return str(e)

    #Get KiCad layer name from Sprint layer index
    def getLayerName(self, layerIdx):
        return sprintLayerMap.get(layerIdx, "Dwgs.User")

    #SOLDERMASK=true elements get an opening copy on the mask layer
    #front side (C1/S1/I1) -> F.Mask, back side (C2/S2/I2) -> B.Mask, rest -> None
    def maskLayerFor(self, layerIdx):
        if layerIdx in (LAYER_C1, LAYER_S1, LAYER_I1):
            return 'F.Mask'
        if layerIdx in (LAYER_C2, LAYER_S2, LAYER_I2):
            return 'B.Mask'
        return None

    def writeHeader(self, f, centroid):
        layer = self.getLayerName(self.comp.layerIdx)
        name = self.footprintName.replace('"', '\\"')
        f.write(f'(footprint "{name}"\n')
        f.write(f'  (version 20241229)\n')
        f.write(f'  (generator "sprint_converter")\n')
        f.write(f'  (layer "{layer}")\n')
        f.write(f'  (uuid {uuid4()})\n')

        #Reference property
        if self.forLibrary:
            refName, refHide = 'REF**', 'no'
        else:
            refName = self.comp.idText.text if self.comp.idText.text else 'REF**'
            refHide = 'no' if self.comp.idText.visible and self.comp.idText.text else 'yes'
        refName = refName.replace('"', '\\"')
        refPos = self.comp.idText.pos
        refX, refY = r2(refPos[0] - centroid[0]), r2(refPos[1] - centroid[1])
        refRotation = sprintAngleToKicad(self.comp.idText.rotation)
        refLayer = self.getLayerName(self.comp.idText.layerIdx)
        refHeight = r2(self.comp.idText.height) if self.comp.idText.height else 1.27
        f.write(f'  (property "Reference" "{refName}" (at {refX} {refY} {refRotation})'
            f' (layer "{refLayer}") (hide {refHide}) (uuid {uuid4()})'
            f' (effects (font (size {refHeight} {refHeight}) (thickness 0.15))))\n')

        #Value property
        if self.forLibrary:
            valName, valHide = self.footprintName, 'yes'
        else:
            valName = self.comp.valueText.text if self.comp.valueText.text else ''
            valHide = 'no' if self.comp.valueText.visible and self.comp.valueText.text else 'yes'
        valName = valName.replace('"', '\\"')
        valPos = self.comp.valueText.pos
        valX, valY = r2(valPos[0] - centroid[0]), r2(valPos[1] - centroid[1])
        valRotation = sprintAngleToKicad(self.comp.valueText.rotation)
        valLayer = self.getLayerName(self.comp.valueText.layerIdx)
        valHeight = r2(self.comp.idText.height) if self.comp.idText.height else 1.27
        f.write(f'  (property "Value" "{valName}" (at {valX} {valY} {valRotation})'
            f' (layer "{valLayer}") (hide {valHide}) (uuid {uuid4()})'
            f' (effects (font (size {valHeight} {valHeight}) (thickness 0.15))))\n')

        #Footprint property (library source)
        f.write(f'  (property "Footprint" "" (at 0 0 0) (unlocked yes)'
            f' (layer "{layer.replace(".Cu", ".Fab")}") (hide yes) (uuid {uuid4()})'
            f' (effects (font (size 1 1) (thickness 0.15))))\n')

        #Attribute (SMD/through-hole)
        f.write(f'  (attr {self.comp.getMountingType()})\n')

    def writeElements(self, f, centroid):
        self._padSeq = 0
        self._writeElemList(f, self.comp.elements, centroid)

    #Depth-first element writer, going through groups. Pad order matches the
    #board exporter, so library and board pad numbers are identical.
    def _writeElemList(self, f, elems, centroid):
        for elem in elems:
            if isinstance(elem, SprintTrack):
                self._writeTrack(f, elem, centroid)
            elif isinstance(elem, SprintPad):
                self._padSeq += 1
                self._writePad(f, elem, centroid, self._padSeq if self.forLibrary else None)
            elif isinstance(elem, SprintPolygon):
                self._writeZone(f, elem, centroid)
            elif isinstance(elem, SprintText):
                self._writeText(f, elem, centroid)
            elif isinstance(elem, SprintCircle):
                self._writeCircle(f, elem, centroid)
            elif isinstance(elem, SprintGroup):
                self._writeElemList(f, elem.elements, centroid)

    #Write track (fp_line)
    def _writeTrack(self, f, track, centroid):
        points = track.points
        if len(points) < 2:
            return
        layer = self.getLayerName(track.layerIdx)
        #SOLDERMASK=true: copper artwork stays, plus an opening copy on mask
        maskLayer = self.maskLayerFor(track.layerIdx) if getattr(track, 'soldermask', None) else None
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            x1, y1 = r2(p1[0] - centroid[0]), r2(p1[1] - centroid[1])
            x2, y2 = r2(p2[0] - centroid[0]), r2(p2[1] - centroid[1])
            f.write(f'    (fp_line (start {x1} {y1}) (end {x2} {y2}) '
                   f'(stroke (width {r2(track.width)}) (type solid)) '
                   f'(layer {layer}) (uuid {uuid4()}))\n')
            if maskLayer:
                f.write(f'    (fp_line (start {x1} {y1}) (end {x2} {y2}) '
                       f'(stroke (width {r2(track.width)}) (type solid)) '
                       f'(layer {maskLayer}) (uuid {uuid4()}))\n')

    #Write pad (pad)
    def _writePad(self, f, pad, centroid, padNoOverride=None):
        layer = self.getLayerName(pad.layerIdx)
        rotation = sprintAngleToKicad(pad.rotation)
        sizeX = r2(max(pad.sizeX, 0.1))
        sizeY = r2(max(pad.sizeY, 0.1))
        x, y = r2(pad.pos[0] - centroid[0]), r2(pad.pos[1] - centroid[1])
        #Sequential number in library mode, else name as numeric, padId, default '1'
        if padNoOverride is not None:
            padNo = str(padNoOverride)
        elif pad.name and pad.name.isdigit():
            padNo = pad.name
        elif pad.padId:
            padNo = str(pad.padId)
        else:
            padNo = '1'

        #Through-hole pad
        if pad.padType == 'PAD':
            padType = "thru_hole"
            if pad.via:
                padLayers = "*.Cu *.Mask"
            elif pad.layerIdx == LAYER_C1:
                padLayers = "F.Cu F.Mask"
            else:
                padLayers = "B.Cu B.Mask"
            drillDef = f'(drill {r2(pad.drill)})'
            if pad.form == PAD_FORM_SQUARE:
                shape = "rect"
            elif pad.form == PAD_FORM_RECT_H:
                shape = "rect"
                sizeX = r2(sizeX * 2)
            elif pad.form == PAD_FORM_RECT_V:
                shape = "rect"
                sizeY = r2(sizeY * 2)
            elif pad.form in (PAD_FORM_RECT_ROUND_H, PAD_FORM_RECT_OCTAGON_H):
                shape = "oval"
                sizeX = r2(sizeX * 2)
            elif pad.form in (PAD_FORM_RECT_ROUND_V, PAD_FORM_RECT_OCTAGON_V):
                shape = "oval"
                sizeY = r2(sizeY * 2)
            else:
                shape = "circle"
        else: #SMD pad
            padType = "smd"
            if layer.endswith(".Cu"):
                padLayers = f'{layer} {layer.replace(".Cu", ".Mask")} {layer.replace(".Cu", ".Paste")}'
            else:
                padLayers = layer
            drillDef = ""
            shape = "rect"

        f.write(f'    (pad "{padNo}" {padType} {shape} (at {x} {y} {rotation}) '
               f'(size {sizeX} {sizeY}) {drillDef} (layers {padLayers}) (uuid {uuid4()}))\n')

    #Write polygon zone (fp_poly)
    def _writeZone(self, f, zone, centroid):
        rawLayer = self.getLayerName(zone.layerIdx)
        layer = rawLayer
        if zone.cutout and rawLayer.endswith('.Cu'):
            layer = "Cmts.User"
        pts = [(r2(p[0] - centroid[0]), r2(p[1] - centroid[1])) for p in zone.points]
        f.write('    (fp_poly\n')
        f.write('      (pts\n')
        for x, y in pts:
            f.write(f'        (xy {x} {y})\n')
        f.write('      )\n')
        f.write(f'      (layer {layer}) (stroke (width {r2(zone.width)}) (type solid)) (fill yes) (uuid {uuid4()})\n')
        f.write('    )\n')
        #SOLDERMASK=true: copper artwork stays, plus an opening copy on mask
        hasMaskFlag = getattr(zone, 'soldermask', None) or getattr(zone, 'soldermaskCutout', None)
        if hasMaskFlag and not (zone.cutout and rawLayer.endswith('.Cu')):
            maskLayer = self.maskLayerFor(zone.layerIdx)
            if maskLayer:
                f.write('    (fp_poly\n')
                f.write('      (pts\n')
                for x, y in pts:
                    f.write(f'        (xy {x} {y})\n')
                f.write('      )\n')
                f.write(f'      (layer {maskLayer}) (stroke (width {r2(zone.width)}) (type solid)) (fill yes) (uuid {uuid4()})\n')
                f.write('    )\n')

    #Write text (fp_text user)
    def _writeText(self, f, text, centroid):
        layer = self.getLayerName(text.layerIdx)
        content = text.text.replace('"', '\\"')
        rotation = sprintAngleToKicad(text.rotation)
        isMirrored = text.mirrorH
        if text.mirrorV:
            isMirrored = not isMirrored
            rotation = (rotation + 180) % 360
        justify = " (justify mirror)" if isMirrored else ""
        height = r2(text.height) if text.height else 1.27
        x, y = r2(text.pos[0] - centroid[0]), r2(text.pos[1] - centroid[1])
        f.write(f'    (fp_text user "{content}" (at {x} {y} {rotation}) (layer {layer}) (uuid {uuid4()})\n')
        f.write(f'      (effects (font (size {height} {height})){justify})\n')
        f.write(f'    )\n')
        #SOLDERMASK=true: opening copy on mask layer
        maskLayer = self.maskLayerFor(text.layerIdx) if getattr(text, 'soldermask', None) else None
        if maskLayer:
            f.write(f'    (fp_text user "{content}" (at {x} {y} {rotation}) (layer {maskLayer}) (uuid {uuid4()})\n')
            f.write(f'      (effects (font (size {height} {height})){justify})\n')
            f.write(f'    )\n')

    #Write circle/arc (fp_circle / fp_arc)
    def _writeCircle(self, f, circle, centroid):
        layer = self.getLayerName(circle.layerIdx)
        self._writeCircleOnLayer(f, circle, centroid, layer)
        #SOLDERMASK=true: opening copy on mask layer
        maskLayer = self.maskLayerFor(circle.layerIdx) if getattr(circle, 'soldermask', None) else None
        if maskLayer:
            self._writeCircleOnLayer(f, circle, centroid, maskLayer)

    #Draw circle/arc on the given layer, used for the mask copy too
    def _writeCircleOnLayer(self, f, circle, centroid, layer):
        cx, cy = r2(circle.center[0] - centroid[0]), r2(circle.center[1] - centroid[1])
        fill = 'yes' if circle.fill else 'no'
        start = r2(circle.start)
        stop = r2(circle.stop)

        #Full circle
        if start == stop:
            endX = r2(cx + circle.radius)
            endY = cy
            f.write(f'    (fp_circle (center {cx} {cy}) (end {endX} {endY}) '
                   f'(stroke (width {r2(circle.width)}) (type solid)) (fill {fill}) '
                   f'(layer {layer}) (uuid {uuid4()}))\n')
        elif circle.fill:
            #Filled arc (e.g. filled semicircle): arcs cannot represent a filled
            #half-disk, export as polygon with one point every 10 degrees
            self._writeArcPolygon(f, circle, centroid, layer)
        else: #Arc
            arcStart, mid, arcEnd = circle.calcStartEndMidPoint()
            sx = r2(arcStart[0] - centroid[0])
            sy = r2(arcStart[1] - centroid[1])
            mx = r2(mid[0] - centroid[0])
            my = r2(mid[1] - centroid[1])
            ex = r2(arcEnd[0] - centroid[0])
            ey = r2(arcEnd[1] - centroid[1])
            f.write(f'    (fp_arc (start {sx} {sy}) (mid {mx} {my}) (end {ex} {ey}) '
                   f'(stroke (width {r2(circle.width)}) (type solid)) (fill {fill}) '
                   f'(layer {layer}) (uuid {uuid4()}))\n')

    #Write filled arc as polygon with one point every 10 degrees (fp_poly).
    #The polygon auto-closes, forming the filled half-disk (arc + chord).
    def _writeArcPolygon(self, f, circle, centroid, layer):
        sweep = (circle.stop - circle.start) % 360
        if sweep == 0:
            sweep = 360
        steps = max(int(math.ceil(sweep / 10.0)), 1)
        cx0, cy0 = circle.center
        pts = []
        for i in range(steps + 1):
            angle = math.radians(circle.start + sweep * i / steps)
            x = r2(cx0 + circle.radius * math.cos(angle) - centroid[0])
            y = r2(cy0 - circle.radius * math.sin(angle) - centroid[1])
            pts.append((x, y))
        f.write('    (fp_poly\n')
        f.write('      (pts\n')
        for x, y in pts:
            f.write(f'        (xy {x} {y})\n')
        f.write('      )\n')
        f.write(f'      (layer {layer}) (stroke (width {r2(circle.width)}) (type solid)) (fill yes) (uuid {uuid4()})\n')
        f.write('    )\n')

    def writeFooter(self, f):
        f.write(')\n')
