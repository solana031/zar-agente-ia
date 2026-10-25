"""Rank actual frames by visible detail and novelty; never synthesize evidence."""
import io
from PIL import Image,ImageFilter,ImageStat


def informative_indices(contents,limit=12):
    scored=[]
    for index,raw in enumerate(contents[:40]):
        try:
            with Image.open(io.BytesIO(raw)) as image:
                gray=image.convert('L');small=gray.resize((16,16));values=list(small.getdata());mean=sum(values)/len(values)
                signature=tuple(v>mean for v in values)
                score=ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]+ImageStat.Stat(gray).stddev[0]*.2
                if ImageStat.Stat(gray).stddev[0]<3:continue
                scored.append((score,index,signature))
        except (ValueError,OSError):continue
    chosen=[];signatures=[]
    for score,index,signature in sorted(scored,reverse=True):
        if any(sum(x!=y for x,y in zip(signature,old))<8 for old in signatures):continue
        chosen.append(index);signatures.append(signature)
        if len(chosen)>=limit:break
    return sorted(chosen)
