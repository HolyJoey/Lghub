import sys,re,struct,os
d=open(sys.argv[1],'rb').read(); out=sys.argv[2]; os.makedirs(out,exist_ok=True)
for m in re.finditer(b'MZ\x90\x00',d):
    o=m.start()
    if o==0: continue
    pe=o+struct.unpack_from('<I',d,o+0x3c)[0]
    if d[pe:pe+4]!=b'PE\0\0': continue
    nsec=struct.unpack_from('<H',d,pe+6)[0]; opt=pe+24; so=opt+struct.unpack_from('<H',d,pe+20)[0]
    end=max(sum(struct.unpack_from('<II',d,so+40*k+16)) for k in range(nsec))
    magic=struct.unpack_from('<H',d,opt)[0]; dd=opt+(112 if magic==0x20b else 96)
    cva,csz=struct.unpack_from('<II',d,dd+8*4)
    if csz and cva>=end: end=cva+csz
    blob=d[o:o+end]
    nm=re.search(rb'OriginalFilename\x00\x00((?:[\x20-\x7e]\x00)+)',blob)
    nm=nm.group(1).decode('utf-16le') if nm else 'pe_%d.bin'%o
    open(os.path.join(out,nm),'wb').write(blob); print(o,end,nm)
