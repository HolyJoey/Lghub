import sys,os,struct,zlib
SIG=bytes([0x8b,0x12,0x02,0xb9,0x6a,0x61,0x20,0x38,0x72,0x7b,0x93,0x02,0x14,0xd7,0xa0,0x32,0x13,0xf5,0xb9,0xe6,0xef,0xae,0x33,0x18,0xee,0x3b,0x2d,0xce,0x24,0xb3,0x6a,0xae])
d=open(sys.argv[1],'rb').read(); out=sys.argv[2]
i=d.find(SIG); hdr=struct.unpack_from('<q',d,i-8)[0]
p=hdr
def rstr():
    global p
    n=0;sh=0
    while True:
        b=d[p];p+=1;n|=(b&0x7f)<<sh;sh+=7
        if b<0x80:break
    s=d[p:p+n].decode();p+=n;return s
maj,mi,cnt=struct.unpack_from('<IIi',d,p);p+=12
bid=rstr()
if maj>=2: p+=8*4+8
print('bundle v%d.%d files=%d id=%s'%(maj,mi,cnt,bid))
for _ in range(cnt):
    off,size=struct.unpack_from('<qq',d,p);p+=16
    csz=0
    if maj>=6: csz=struct.unpack_from('<q',d,p)[0];p+=8
    typ=d[p];p+=1;path=rstr()
    blob=d[off:off+(csz or size)]
    if csz: blob=zlib.decompress(blob,-15)
    dst=os.path.join(out,path.replace('\\','/'))
    assert os.path.realpath(dst).startswith(os.path.realpath(out))
    os.makedirs(os.path.dirname(dst),exist_ok=True);open(dst,'wb').write(blob)
    print(typ,size,path)
