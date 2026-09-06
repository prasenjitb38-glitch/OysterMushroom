(async function(){
  const grid=document.getElementById("chart-grid");if(!grid)return;
  const empty=document.getElementById("chart-empty"),error=document.getElementById("chart-error");
  try{
    const response=await fetch(grid.dataset.url,{headers:{"Accept":"application/json"}});
    const payload=await response.json();if(!response.ok)throw new Error(payload.error||"Request failed");
    if(payload.empty){empty.hidden=false;return}
    if(typeof Chart==="undefined")throw new Error("Chart library unavailable");
    const colors=["#157052","#e67e22","#2463a6","#9b59b6"];
    payload.charts.forEach((chart,index)=>{
      const card=document.createElement("section");card.className="chart-card";
      const title=document.createElement("h2");title.textContent=chart.title;
      const canvas=document.createElement("canvas");canvas.setAttribute("aria-label",chart.title);canvas.setAttribute("role","img");
      card.append(title,canvas);grid.append(card);
      new Chart(canvas,{type:index===5||index===6?"bar":"line",data:{labels:chart.labels,datasets:chart.datasets.map((set,i)=>({...set,borderColor:colors[i%colors.length],backgroundColor:colors[i%colors.length]+"44",tension:.25,fill:false}))},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"bottom"},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${c.dataset.unit==="₹"?"₹":""}${Number(c.raw).toLocaleString(undefined,{maximumFractionDigits:2})}${c.dataset.unit==="Kg"?" Kg":""}`}}},scales:{x:{ticks:{maxRotation:35,minRotation:0}},y:{beginAtZero:true}}}});
    });
  }catch(e){console.error(e);error.hidden=false}
})();
