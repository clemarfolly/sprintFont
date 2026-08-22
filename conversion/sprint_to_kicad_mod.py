#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#Convert Sprint-Layout components to KiCad footprint files (.kicad_mod)
#Footprint format: https://dev-docs.kicad.org/en/file-formats/sexpr-intro/index.html#_footprint
#Author: cdhigh <https://github.com/cdhigh>, clemarfolly <https://github.com/clemarfolly>
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
    def __init__(self, comp, footprintName=''):
        self.comp = comp
        self.footprintName = footprintName or comp.comment or comp.idText.text or 'Footprint'

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

    def writeHeader(self, f, centroid):
        layer = self.getLayerName(self.comp.layerIdx)
        name = self.footprintName.replace('"', '\\"')
        f.write(f'(footprint "{name}"\n')
        f.write(f'  (version 20241229)\n')
        f.write(f'  (generator "sprint_converter")\n')
        f.write(f'  (layer "{layer}")\n')
        f.write(f'  (uuid {uuid4()})\n')

        #Reference property
        refName = self.comp.idText.text if self.comp.idText.text else 'REF**'
        refName = refName.replace('"', '\\"')
        refPos = self.comp.idText.pos
        refX, refY = r2(refPos[0] - centroid[0]), r2(refPos[1] - centroid[1])
        refRotation = sprintAngleToKicad(self.comp.idText.rotation)
        refLayer = self.getLayerName(self.comp.idText.layerIdx)
        refHide = 'no' if self.comp.idText.visible and self.comp.idText.text else 'yes'
        refHeight = r2(self.comp.idText.height) if self.comp.idText.height else 1.27
        f.write(f'  (property "Reference" "{refName}" (at {refX} {refY} {refRotation})'
            f' (layer "{refLayer}") (hide {refHide}) (uuid {uuid4()})'
            f' (effects (font (size {refHeight} {refHeight}) (thickness 0.15))))\n')

        #Value property
        valName = self.comp.valueText.text if self.comp.valueText.text else ''
        valName = valName.replace('"', '\\"')
        valPos = self.comp.valueText.pos
        valX, valY = r2(valPos[0] - centroid[0]), r2(valPos[1] - centroid[1])
        valRotation = sprintAngleToKicad(self.comp.valueText.rotation)
        valLayer = self.getLayerName(self.comp.valueText.layerIdx)
        valHide = 'no' if self.comp.valueText.visible and self.comp.valueText.text else 'yes'
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
        for elem in self.comp.elements:
            if isinstance(elem, SprintTrack):
                self._writeTrack(f, elem, centroid)
            elif isinstance(elem, SprintPad):
                self._writePad(f, elem, centroid)
            elif isinstance(elem, SprintPolygon):
                self._writeZone(f, elem, centroid)
            elif isinstance(elem, SprintText):
                self._writeText(f, elem, centroid)
            elif isinstance(elem, SprintCircle):
                self._writeCircle(f, elem, centroid)

    #Write track (fp_line)
    def _writeTrack(self, f, track, centroid):
        points = track.points
        if len(points) < 2:
            return
        layer = self.getLayerName(track.layerIdx)
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            x1, y1 = r2(p1[0] - centroid[0]), r2(p1[1] - centroid[1])
            x2, y2 = r2(p2[0] - centroid[0]), r2(p2[1] - centroid[1])
            f.write(f'    (fp_line (start {x1} {y1}) (end {x2} {y2}) '
                   f'(stroke (width {r2(track.width)}) (type solid)) '
                   f'(layer {layer}) (uuid {uuid4()}))\n')

    #Write pad (pad)
    def _writePad(self, f, pad, centroid):
        layer = self.getLayerName(pad.layerIdx)
        rotation = sprintAngleToKicad(pad.rotation)
        sizeX = r2(max(pad.sizeX, 0.1))
        sizeY = r2(max(pad.sizeY, 0.1))
        x, y = r2(pad.pos[0] - centroid[0]), r2(pad.pos[1] - centroid[1])
        #name as numeric takes priority, then padId, default to '1'
        padNo = '1'
        if pad.name and pad.name.isdigit():
            padNo = pad.name
        elif pad.padId:
            padNo = str(pad.padId)

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
        layer = self.getLayerName(zone.layerIdx)
        if zone.cutout and layer.endswith('.Cu'):
            layer = "Cmts.User"
        f.write('    (fp_poly\n')
        f.write('      (pts\n')
        for p in zone.points:
            f.write(f'        (xy {r2(p[0] - centroid[0])} {r2(p[1] - centroid[1])})\n')
        f.write('      )\n')
        f.write(f'      (layer {layer}) (stroke (width {r2(zone.width)}) (type solid)) (fill yes) (uuid {uuid4()})\n')
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

    #Write circle/arc (fp_circle / fp_arc)
    def _writeCircle(self, f, circle, centroid):
        layer = self.getLayerName(circle.layerIdx)
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

    def writeFooter(self, f):
        f.write(')\n')
