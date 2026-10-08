"""Shared charts from explicit numeric datasets; never synthesizes measurements."""
import io,math

KINDS={'bar','line','area','pie','donut','scatter'}
def render(spec):
    from PIL import Image,ImageDraw,ImageFont
    kind=spec.get('type','bar');values=[float(v) for v in spec.get('values',[])]
    if kind not in KINDS or not 1<=len(values)<=200 or not all(math.isfinite(v) for v in values):raise ValueError('Tipo y datos numéricos explícitos requeridos para el gráfico.')
    labels=[str(x) for x in spec.get('labels',range(1,len(values)+1))]
    if len(labels)!=len(values):raise ValueError('Etiquetas y valores deben coincidir.')
    image=Image.new('RGB',(1000,580),'#f7f6f2');draw=ImageDraw.Draw(image);font=ImageFont.load_default(size=17)
    draw.text((40,25),str(spec.get('title','Gráfico'))[:100],fill='#173854',font=ImageFont.load_default(size=25))
    colors=['#173854','#bf914e','#48776c','#867095','#8f5f47','#537da8']
    if kind in {'pie','donut'}:
        if min(values)<0 or sum(values)<=0:raise ValueError('Pie/donut requieren valores no negativos y total positivo.')
        angle=-90
        for i,v in enumerate(values):
            end=angle+360*v/sum(values);draw.pieslice((80,85,510,515),angle,end,fill=colors[i%len(colors)]);angle=end
            if i<14:draw.rectangle((565,90+i*29,581,106+i*29),fill=colors[i%len(colors)]);draw.text((595,87+i*29),labels[i][:28]+' · '+format(v,'.4g'),fill='#173854',font=font)
        if kind=='donut':draw.ellipse((208,213,382,387),fill='#f7f6f2')
    else:
        low=min(0,min(values));high=max(0,max(values));span=high-low or 1
        xvalues=[float(v) for v in spec.get('x',range(len(values)))]
        if len(xvalues)!=len(values) or not all(math.isfinite(v) for v in xvalues):raise ValueError('X e Y deben contener pares numéricos válidos.')
        xmin=min(xvalues);xspan=max(xvalues)-xmin or 1
        x=lambda i:90+(xvalues[i]-xmin)/xspan*800
        y=lambda v:490-(v-low)/span*380
        for i in range(5):
            value=low+span*i/4;yy=y(value);draw.line((85,yy,925,yy),fill='#ddd9d1');draw.text((10,yy-8),format(value,'.4g'),fill='#173854',font=font)
        points=[(x(i),y(v)) for i,v in enumerate(values)]
        if kind=='bar':
            width=min(45,650/len(values))
            for xx,yy in points:draw.rectangle((xx-width/2,min(yy,y(0)),xx+width/2,max(yy,y(0))),fill=colors[0])
        elif kind=='scatter':
            for xx,yy in points:draw.ellipse((xx-5,yy-5,xx+5,yy+5),fill=colors[0])
        else:
            if kind=='area':draw.polygon([(points[0][0],y(0))]+points+[(points[-1][0],y(0))],fill='#d2be9b')
            if len(points)>1:draw.line(points,fill=colors[0],width=4)
            else:draw.ellipse((points[0][0]-4,points[0][1]-4,points[0][0]+4,points[0][1]+4),fill=colors[0])
        step=max(1,math.ceil(len(labels)/8))
        for i in range(0,len(labels),step):draw.text((x(i)-20,510),labels[i][:14],fill='#173854',font=font)
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()
