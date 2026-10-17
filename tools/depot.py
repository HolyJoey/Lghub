import sys,struct,json,os
d=open(sys.argv[1],'rb').read(); out=sys.argv[2]; os.makedirs(out,exist_ok=True)
magic,hl=struct.unpack_from('<II',d,0); assert magic==0x20170110
h=json.loads(d[8:8+hl]); p=8+hl
for f in h['files']:
    n=struct.unpack_from('<I',d,p)[0]; p+=4
    if n==0xffffffff or p+n>len(d): n=struct.unpack_from('<Q',d,p-4)[0]; p+=4
    dst=os.path.join(out,f['name']); assert os.path.realpath(dst).startswith(os.path.realpath(out))
    os.makedirs(os.path.dirname(dst),exist_ok=True); open(dst,'wb').write(d[p:p+n]); p+=n
    print(f['name'],n)
print('trailing bytes',len(d)-p)
