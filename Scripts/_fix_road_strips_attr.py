path = 'D:/VirtualCity/Scripts/_road_strips_v2.py'
c = open(path, encoding='utf-8').read()

OLD = """hw_attrib = geo.addAttrib(hou.attribType.Prim, 'half_width', 0.0)
is_junc_a = geo.addAttrib(hou.attribType.Prim, 'is_junction', 0)"""

NEW = """def _get_or_add(geo, atype, name, default):
    a = geo.findPrimAttrib(name) if atype == hou.attribType.Prim else None
    return a if a else geo.addAttrib(atype, name, default)
hw_attrib = _get_or_add(geo, hou.attribType.Prim, 'half_width', 0.0)
is_junc_a = _get_or_add(geo, hou.attribType.Prim, 'is_junction', 0)"""

if OLD in c:
    c = c.replace(OLD, NEW, 1)
    open(path, 'w', encoding='utf-8', newline='\n').write(c)
    print('fixed')
else:
    print('not found')
