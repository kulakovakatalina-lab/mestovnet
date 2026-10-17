"""Measure protected regions against actual text pixels and the full rotating disc."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

PROFILE = 'reels-project-safe-areas-v1'
# Project margins. They do not claim to reproduce every Instagram UI version/device.
UI_MASKS = {'top':[0,0,1080,180], 'right':[960,400,1080,1760],
            'bottom':[0,1750,1080,1920]}


def measure(work, selected, vinyl_box, *, mode='contain'):
    work = Path(work)
    placement = json.loads((work/'source-placement.json').read_text())
    with Image.open(work/'base.png') as image:
        preview = image.convert('RGBA')
    text = Image.new('RGBA',preview.size)
    for name in ('title.png','facts.png','brand.png'):
        with Image.open(work/name) as image:
            text = Image.alpha_composite(text,image.convert('RGBA'))
    alpha = text.getchannel('A')
    x,y,size = vinyl_box
    circle = Image.new('L',preview.size)
    ImageDraw.Draw(circle).ellipse((x,y,x+size-1,y+size-1),fill=255)
    analysis = selected.get('analysis',{})
    issues=[]; records=[]
    if not analysis or analysis.get('conflicts'):
        issues.append('source_analysis_missing_or_conflicting')
    if analysis.get('kind') in ('poster','collage','unknown'):
        issues.append('unsuitable_background_kind')
    if (analysis.get('kind')=='group_photo' or len(analysis.get('figures',[]))>1) and not analysis.get('faces'):
        issues.append('incomplete_group_face_analysis')
    def count(mask, box):
        hist=mask.crop(box).histogram()
        return sum(hist[1:])
    for kind in ('faces','figures','important_regions','watermark_regions','text_regions'):
        for index,region in enumerate(analysis.get(kind,[])):
            for zoom in ((1,1.035) if mode=='cover' else (1,)):
                w,h=placement['source_size'];scale=placement['scale']*zoom
                ox=(1080-w*scale)/2;oy=(1920-h*scale)/2
                box=[round(region[0]*w*scale+ox),round(region[1]*h*scale+oy),
                     round(region[2]*w*scale+ox),round(region[3]*h*scale+oy)]
                cropped=box[0]<0 or box[1]<0 or box[2]>1080 or box[3]>1920
                overlap_text=count(alpha,box);overlap_disc=count(circle,box)
                records.append(dict(kind=kind,index=index,zoom=zoom,box=box,
                    cropped=cropped,text_pixels=overlap_text,disc_pixels=overlap_disc))
                if cropped:issues.append('protected_'+kind+'_cropped')
                if overlap_text or overlap_disc:issues.append('protected_'+kind+'_overlap')
    for name,box in UI_MASKS.items():
        if count(alpha,box):issues.append('text_in_ui_'+name)
    layout=json.loads((work/'text-layout.json').read_text())
    first_y=min(item['box'][1] for item in layout)
    if first_y-y-size<115:issues.append('vinyl_text_gap_below_115')
    overlay=Image.new('RGBA',preview.size);draw=ImageDraw.Draw(overlay)
    for name,box in UI_MASKS.items():
        draw.rectangle(box,fill=(230,20,80,55));draw.text((box[0]+4,box[1]+4),name,fill='white')
    with Image.open(work/'vinyl-preview.png') as disc:
        preview.alpha_composite(disc,(x,y))
    preview=Image.alpha_composite(preview,text)
    Image.alpha_composite(preview,overlay).convert('RGB').resize((405,720)).save(work/'ui-preview.jpg')
    result=dict(profile=PROFILE,ui_masks=UI_MASKS,source_mode=mode,protected=records,
                first_text_y=first_y,vinyl_text_gap=first_y-y-size,issues=sorted(set(issues)),
                method='actual_text_alpha_and_rotating_disc_envelope; protected_bounding_boxes')
    (work/'composition.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
