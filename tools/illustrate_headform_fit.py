"""Compose headform test figures from measured JSON and actual Blender renders."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--sections',type=Path,required=True)
    parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--font',type=Path,default=Path('/System/Library/Fonts/Hiragino Sans GB.ttc'))
    args=parser.parse_args();report=json.loads(args.report.read_text());section=json.loads(args.sections.read_text())
    if report['source_sha256']!=section['source_sha256']:raise ValueError('Source mismatch')
    ink,muted,red,green,bg='#203746','#647887','#BB3544','#278B76','#F8FAFB'
    scale=2
    def canvas(w,h):
        image=Image.new('RGB',(w*scale,h*scale),bg);return image,ImageDraw.Draw(image)
    def text(draw,x,y,value,size=24,color=ink):
        draw.text((x*scale,y*scale),value,font=ImageFont.truetype(str(args.font),size*scale),fill=color,anchor='lt')
    def line(draw,points,color,width=1):draw.line([(x*scale,y*scale) for x,y in points],fill=color,width=width*scale)
    def header(draw,title):
        text(draw,60,36,'PROJECT PULSAR / PARAMETRIC HEADFORM TEST',19,muted)
        text(draw,60,78,title,40)
        text(draw,60,140,'头高 230 · 头宽 135 · 头围 590 · 瞳高 127 · 瞳距 65 mm',26)
        text(draw,60,184,'两种尺寸包络均匹配输入尺寸；头长与轮廓属于建模假设。',22,muted)
    titles={'Ellipse':'A  椭圆截面头模','Rounded':'B  方圆截面头模'}
    im,draw=canvas(2000,1430);header(draw,'头模试戴 · 三维碰撞结果')
    for i,case in enumerate(report['cases']):
        x=60+i*990
        text(draw,x,253,titles[case['label']],30)
        text(draw,x,301,f"由截面假设推算的头长：{case['implied_head_length_mm']:.1f} mm",23,muted)
        with Image.open(args.images/f"headform-{case['label'].lower()}-cutaway.png") as source:
            preview=source.convert('RGB').resize((900*scale,900*scale),Image.Resampling.LANCZOS)
            im.paste(preview,(x*scale,350*scale))
        status='无相交' if case['collision_free'] else '检出前壳、后壳相交'
        text(draw,x,1265,status,29,green if case['collision_free'] else red)
        text(draw,x+430,1271,'左右直视线：通过' if all(not ray['blocked'] for ray in case['pupil_rays']) else '直视线：受阻',23,green)
    line(draw,[(60,1330),(1940,1330)],'#D5DFE5')
    text(draw,60,1350,'绿色为参数头模；红色为与完整装配相交的头模三角面。外壳裁去一半仅用于观察。',22,muted)
    text(draw,60,1391,'此结果只针对所建包络与测试姿态，不能代替真实头型、内衬和佩戴／取下过程验证。',21,muted)
    im.save(args.images/'headform-fit-comparison.png')

    im,draw=canvas(2000,1420);header(draw,'头模试戴 · 正中剖面叠合')
    for i,case in enumerate(report['cases']):
        cx=500+i*1000;cy=805;factor=2.65
        transform=lambda p:(cx+p[0]*factor,cy-p[1]*factor)
        text(draw,cx-390,255,titles[case['label']],30)
        text(draw,cx-390,303,f"推算头长 {case['implied_head_length_mm']:.1f} mm；瞳孔 Z = {case['placement']['eye_z_mm']:+.0f} mm",22,muted)
        for mm in range(-140,161,20):
            line(draw,[transform((-140,mm)),transform((140,mm))],'#E2E8EC')
        for mm in range(-140,141,20):
            line(draw,[transform((mm,-160)),transform((mm,160))],'#E2E8EC')
        points=[transform(p) for p in case['side_outline_yz_mm']]
        draw.polygon([(round(x*scale),round(y*scale)) for x,y in points],fill='#C4E7DF')
        line(draw,[*points,points[0]],green,2)
        for loops,color in zip(section['side_section'],('#317DA1','#D69546')):
            mask=Image.new('1',im.size,0)
            for loop in loops:
                layer=Image.new('1',im.size,0)
                ImageDraw.Draw(layer).polygon([(round(x*scale),round(y*scale)) for x,y in map(transform,loop)],fill=1)
                mask=ImageChops.logical_xor(mask,layer)
            im.paste(color,mask=mask)
        eye=case['pupil_rays'][0]['origin_xyz_mm'];px,py=transform(eye[1:])
        draw.ellipse(((px-5)*scale,(py-5)*scale,(px+5)*scale,(py+5)*scale),fill='#BD4759')
        line(draw,[(px,py),(cx+365,py)],'#BD4759',2)
        text(draw,cx+190,py-39,'瞳孔侧向投影',19,'#BD4759')
        chin_z=case['offset_xyz_mm'][2]
        # Dimension endpoints are at the measured chin and eye elevations.
        dimension_x=cx-350
        top_y=transform((0,eye[2]))[1];bottom_y=transform((0,chin_z))[1]
        line(draw,[(dimension_x,top_y),(dimension_x,bottom_y)],green,2)
        for y in (top_y,bottom_y):line(draw,[(dimension_x-6,y),(dimension_x+6,y)],green,2)
        text(draw,dimension_x+12,(top_y+bottom_y)/2-12,'瞳高 127',20,green)
        text(draw,cx-390,1250,'前后方向的放置搜索余量',21,muted)
        text(draw,cx+10,1245,f"{case['placement']['directional_sample_margin_mm']:+.1f} mm",27,red)
    line(draw,[(60,1310),(1940,1310)],'#D5DFE5')
    text(draw,60,1334,'浅绿轮廓为参数头模；蓝色／橙色为前后壳。瞳孔位于 X = ±32.5 mm，图中为投影，并非正中切面上的眼孔。',20,muted)
    text(draw,60,1375,'负余量表示搜索采样点沿前后方向越过内壁；它不是法线穿透深度。三维碰撞判定另对完整网格及五金进行。',20,muted)
    im.save(args.images/'headform-fit-sections.png')
    print('PASS: comparison and midline overlay figures written')


if __name__=='__main__':main()
