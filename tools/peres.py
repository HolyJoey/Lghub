import sys,struct,os
d=open(sys.argv[1],'rb').read(); out=sys.argv[2] if len(sys.argv)>2 else None
RVA,RAW=0x5b000,0x52800
base=RAW
def name(off,isname):
    if not isname: return str(off)
    o=base+off; n=struct.unpack_from('<H',d,o)[0]; return d[o+2:o+2+2*n].decode('utf-16le')
def walk(off,path):
    o=base+off; nn,ni=struct.unpack_from('<HH',d,o+12)
    for k in range(nn+ni):
        nid,ptr=struct.unpack_from('<II',d,o+16+8*k)
        nm=name(nid&0x7fffffff,nid>>31)
        if ptr>>31: walk(ptr&0x7fffffff,path+[nm])
        else:
            rva,sz=struct.unpack_from('<II',d,base+ptr)
            fo=rva-RVA+RAW; blob=d[fo:fo+sz]
            print('/'.join(path+[nm]),sz,blob[:8])
            if out and sz>100000:
                p=os.path.join(out,'_'.join(path+[nm]).replace('/','_'));open(p,'wb').write(blob)
walk(0,[])
