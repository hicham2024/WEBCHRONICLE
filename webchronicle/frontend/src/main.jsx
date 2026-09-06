import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const API=(import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\\/$/, '');

function App(){
  const [url,setUrl]=useState('');
  const [q,setQ]=useState('');
  const [items,setItems]=useState([]);
  const [msg,setMsg]=useState('');
  const load=()=>fetch(`${API}/api/recent`).then(r=>r.json()).then(setItems);
  useEffect(load,[]);

  async function archive(e){
    e.preventDefault(); setMsg('Capture en cours…');
    const r=await fetch(`${API}/api/archive`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
    const d=await r.json();
    if(!r.ok){setMsg(d.detail||'Erreur'); return}
    setMsg(`Archivé : ${d.code}`); setUrl(''); load();
  }

  async function search(e){
    e.preventDefault();
    if(!q.trim()){load();return}
    const d=await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
    setItems(d);
  }

  return <main>
    <header><h1>WEBCHRONICLE</h1><p>Conserver une copie publique du web, avec date, capture et historique.</p></header>
    <section className="panel">
      <form onSubmit={archive} className="row"><input value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://exemple.com/article"/><button>Archiver</button></form>
      {msg && <div className="msg">{msg}</div>}
      <form onSubmit={search} className="row search"><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Rechercher dans les archives"/><button>Rechercher</button></form>
    </section>
    <section>
      <div className="sectionTitle"><h2>Captures récentes</h2><a href={`${API}/rss`}>RSS</a></div>
      <div className="list">{items.map(x=><article key={x.code}>
        <div className="meta">{x.archived_at} · {x.status_code??'import'} · {x.code}</div>
        <h3>{x.title||'Sans titre'}</h3>
        <a className="source" href={x.original_url} target="_blank">{x.original_url}</a>
        <div className="actions"><a href={`${API}/s/${x.code}`} target="_blank">Snapshot</a><a href={`${API}/shot/${x.code}`} target="_blank">Capture</a><a href={`${API}/api/read/${x.code}`} target="_blank">Mode lecture</a></div>
      </article>)}</div>
    </section>
  </main>
}
createRoot(document.getElementById('root')).render(<App/>);
