import base64,hashlib,importlib.metadata as m,json,sys
result={}
for name in sys.argv[1:]:
    dist=m.distribution(name); checked=0; mismatches=[]
    for f in dist.files:
        if not (str(f).endswith('.py') or str(f).endswith('.so')) or not f.hash:
            continue
        path=dist.locate_file(f)
        actual=base64.urlsafe_b64encode(hashlib.new(f.hash.mode,path.read_bytes()).digest()).decode().rstrip('=')
        if actual!=f.hash.value:
            mismatches.append(str(f))
        checked+=1
    assert checked>0
    result[name]={'version':dist.version,'verified_python_and_extension_files':checked,'mismatches':mismatches}
print(json.dumps(result,indent=2))
assert not any(r['mismatches'] for r in result.values())
