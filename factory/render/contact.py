"""Preview contact sheets for visual review of fixture compositions."""
from pathlib import Path
import textwrap
from PIL import Image, ImageDraw


def sheet(paths, target, *, columns=4, thumb=(180,255), labels=None):
    paths=list(paths)
    rows=max(1,(len(paths)+columns-1)//columns)
    canvas=Image.new('RGB',(columns*(thumb[0]+16)+16,rows*(thumb[1]+50)+16),'#e7eaed')
    draw=ImageDraw.Draw(canvas)
    for i,path in enumerate(paths):
        image=Image.open(path).convert('RGB');image.thumbnail(thumb)
        x=16+(i%columns)*(thumb[0]+16);y=16+(i//columns)*(thumb[1]+50)
        canvas.paste(image,(x+(thumb[0]-image.width)//2,y))
        label=labels[i] if labels else Path(path).stem
        draw.multiline_text((x,y+thumb[1]+5),'\n'.join(textwrap.wrap(label,width=max(12,thumb[0]//6))),fill='#222222',spacing=2)
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True);canvas.save(target)
    return target
