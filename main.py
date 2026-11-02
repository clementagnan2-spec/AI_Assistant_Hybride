import json, os, threading, urllib.request, tkinter as tk
from tkinter import ttk, messagebox
APP=os.path.join(os.getenv("APPDATA",os.path.expanduser("~")),"AIAssistantHybride")
os.makedirs(APP,exist_ok=True)
CFG=os.path.join(APP,"config.json"); HIST=os.path.join(APP,"history.json")
DEFAULT={"mode":"local","local_url":"http://localhost:11434/api/chat","local_model":"qwen2.5:0.5b","online_url":"https://api.openai.com/v1/chat/completions","online_model":"gpt-4o-mini","api_key":""}
def load(p,d):
 try:
  with open(p,encoding="utf-8") as f:return json.load(f)
 except:return d
def save(p,d):
 with open(p,"w",encoding="utf-8") as f:json.dump(d,f,ensure_ascii=False,indent=2)
class App:
 def __init__(self,r):
  self.r=r; r.title("AI Assistant Hybride"); r.geometry("850x600")
  self.c=load(CFG,DEFAULT.copy()); self.h=load(HIST,[])
  bar=ttk.Frame(r,padding=10);bar.pack(fill="x")
  ttk.Label(bar,text="AI Assistant Hybride",font=("Segoe UI",16,"bold")).pack(side="left")
  self.mode=ttk.Label(bar);self.mode.pack(side="right",padx=8)
  ttk.Button(bar,text="Paramètres",command=self.settings).pack(side="right")
  self.out=tk.Text(r,wrap="word",state="disabled",font=("Segoe UI",11));self.out.pack(fill="both",expand=True,padx=10,pady=6)
  b=ttk.Frame(r,padding=10);b.pack(fill="x")
  self.entry=tk.Text(b,height=3);self.entry.pack(side="left",fill="x",expand=True)
  ttk.Button(b,text="Envoyer",command=self.send).pack(side="left",padx=8)
  self.status=ttk.Label(r,text="Prêt");self.status.pack(anchor="w",padx=12,pady=5)
  for m in self.h:self.show("Vous" if m["role"]=="user" else "IA",m["content"])
  self.update_mode()
 def update_mode(self):self.mode.config(text="Mode : "+("Hors ligne / Ollama" if self.c["mode"]=="local" else "En ligne / API"))
 def show(self,who,msg):
  self.out.config(state="normal");self.out.insert("end",who+"\n"+msg+"\n\n");self.out.see("end");self.out.config(state="disabled")
 def send(self):
  q=self.entry.get("1.0","end").strip()
  if not q:return
  self.entry.delete("1.0","end");self.h.append({"role":"user","content":q});save(HIST,self.h);self.show("Vous",q);self.status.config(text="Réponse en cours…")
  threading.Thread(target=self.ask,daemon=True).start()
 def ask(self):
  try:
   if self.c["mode"]=="local":
    data={"model":self.c["local_model"],"messages":self.h,"stream":False};headers={"Content-Type":"application/json"};url=self.c["local_url"]
   else:
    if not self.c["api_key"].strip():raise Exception("Configure une clé API dans Paramètres.")
    data={"model":self.c["online_model"],"messages":self.h};headers={"Content-Type":"application/json","Authorization":"Bearer "+self.c["api_key"]};url=self.c["online_url"]
   req=urllib.request.Request(url,data=json.dumps(data).encode(),headers=headers)
   with urllib.request.urlopen(req,timeout=300) as res: result=json.loads(res.read().decode())
   answer=result.get("message",{}).get("content","") if self.c["mode"]=="local" else result["choices"][0]["message"]["content"]
   if not answer:answer="Aucune réponse du modèle."
   self.h.append({"role":"assistant","content":answer});save(HIST,self.h);self.r.after(0,lambda:self.done(answer))
  except Exception as e:self.r.after(0,lambda:self.done("Erreur : "+str(e)))
 def done(self,msg):self.show("IA",msg);self.status.config(text="Prêt")
 def settings(self):
  w=tk.Toplevel(self.r);w.title("Paramètres");w.geometry("650x390")
  f=ttk.Frame(w,padding=12);f.pack(fill="both",expand=True);v={}
  fields=[("mode","Mode (local ou online)"),("local_url","URL Ollama"),("local_model","Modèle local"),("online_url","URL API en ligne"),("online_model","Modèle en ligne"),("api_key","Clé API")]
  for i,(k,label) in enumerate(fields):
   ttk.Label(f,text=label).grid(row=i,column=0,sticky="w",pady=6);v[k]=tk.StringVar(value=self.c.get(k,""))
   ttk.Entry(f,textvariable=v[k],width=55,show="*" if k=="api_key" else "").grid(row=i,column=1,sticky="ew",pady=6)
  f.columnconfigure(1,weight=1)
  ttk.Label(f,text="Local : installer Ollama et télécharger le modèle. En ligne : Internet et clé API nécessaires.",wraplength=600).grid(row=6,column=0,columnspan=2,pady=12)
  def store():
   new={k,x.get().strip() for k,x in v.items()}
   self.c.update({k:x.get().strip() for k,x in v.items()})
   if self.c["mode"] not in ("local","online"):messagebox.showerror("Erreur","Mode : local ou online");return
   save(CFG,self.c);self.update_mode();w.destroy()
  ttk.Button(f,text="Enregistrer",command=store).grid(row=7,column=1,sticky="e")
if __name__=="__main__":
 root=tk.Tk();App(root);root.mainloop()
