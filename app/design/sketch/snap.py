import mcp, sys, subprocess, os
nid, out, w, h = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
open(out + ".svg", "w", encoding="utf-8").write(mcp.call("export_svg", ids=[nid])["svg"])
d = os.getcwd()
subprocess.run([r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "--headless=new", "--disable-gpu", "--hide-scrollbars",
  f"--window-size={w},{h}", "--screenshot=" + os.path.join(d, out + ".png"), "file:///" + d.replace("\\", "/") + f"/{out}.svg"], capture_output=True)
print("ok")
