path = 'D:/VirtualCity/Scripts/_patch_osm_import_v2.py'
content = open(path, encoding='utf-8').read()
old = '    """Return height in metres. 0.0 means unknown -> procedural_height fills in."""'
new = '    # Return height in metres. 0.0 means unknown -> procedural_height fills in.'
content = content.replace(old, new, 1)
open(path, 'w', encoding='utf-8', newline='\n').write(content)
print('replaced:', old in open(path, encoding='utf-8').read())
