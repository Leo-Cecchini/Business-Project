// ===== Geoapify Autocomplete =====

(function(){
  const GEOAPIFY_KEY = window.GEOAPIFY_KEY || "";
  if(!GEOAPIFY_KEY){
    console.warn("[Geoapify] Autocomplete disabilitato: imposta window.GEOAPIFY_KEY per abilitarlo.");
  }

  function debounce(fn, ms=300){ let t; return (...args)=>{ clearTimeout(t); t=setTimeout(()=>fn(...args), ms); }; }

  async function geoapifyAutocomplete(q){
    if(!GEOAPIFY_KEY || !q) return [];
    const url = `https://api.geoapify.com/v1/geocode/autocomplete?text=${encodeURIComponent(q)}&limit=7&lang=it&apiKey=${GEOAPIFY_KEY}`;
    const res = await fetch(url);
    if(!res.ok) return [];
    const data = await res.json();
    return (data.features || []).map(f=>f.properties || {});
  }

  function fillAddressFields(props){
    const street = props.street || props.name || "";
    const number = props.housenumber || "";
    const city   = props.city || props.county || props.town || props.village || "";
    const state  = props.country || props.state || "";
    const zip    = props.postcode || "";

    document.getElementById('addrStreet').value = street;
    document.getElementById('addrNumber').value = number;
    document.getElementById('addrCity').value   = city;
    document.getElementById('addrState').value  = state;
    document.getElementById('addrZip').value    = zip;

    const formatted = props.formatted || [ [street, number].filter(Boolean).join(' '), [zip, city].filter(Boolean).join(' '), state ].filter(Boolean).join(', ');
    let hidden = document.getElementById('addrFormatted');
    if(!hidden){
      hidden = document.createElement('input');
      hidden.type='hidden';
      hidden.id='addrFormatted';
      document.getElementById('projectForm').appendChild(hidden);
    }
    hidden.value = formatted;
  }

  function renderSuggestions(box, items, onPick){
    if(!items.length){ box.innerHTML = ""; return; }
    const ul = document.createElement('ul');
    items.forEach(p=>{
      const li = document.createElement('li');
      li.textContent = p.formatted || [p.street, p.housenumber, p.postcode, p.city, p.country].filter(Boolean).join(' ');
      li.addEventListener('click', ()=> onPick(p, li.textContent));
      ul.appendChild(li);
    });
    box.innerHTML = ""; box.appendChild(ul);
  }

  function setupGeoapifyAutocomplete(){
    const input = document.getElementById('addrSearch');
    const box   = document.getElementById('addrSuggest');
    if(!input || !box) return;

    const search = debounce(async ()=>{
      const q = input.value.trim();
      if(q.length < 3){ box.innerHTML = ""; return; }
      try{
        const items = await geoapifyAutocomplete(q);
        renderSuggestions(box, items, (p, label)=>{
          fillAddressFields(p);
          box.innerHTML = "";
          input.value = label;
        });
      }catch(e){
        console.warn(e); box.innerHTML = "";
      }
    }, 300);

    input.addEventListener('input', search);
    input.addEventListener('blur', ()=> setTimeout(()=> box.innerHTML = "", 200));
  }

  function buildAddressFromForm(){
    const street = document.getElementById('addrStreet').value.trim();
    const number = document.getElementById('addrNumber').value.trim();
    const city   = document.getElementById('addrCity').value.trim();
    const state  = document.getElementById('addrState').value.trim();
    const zip    = document.getElementById('addrZip').value.trim();
    const formattedHidden = document.getElementById('addrFormatted')?.value.trim();

    const formatted = formattedHidden || [ [street, number].filter(Boolean).join(' '), [zip, city].filter(Boolean).join(' '), state ].filter(Boolean).join(', ');
    return {
      formatted: formatted || (city || ''),
      street: street || null,
      street_number: number || null,
      city: city || null,
      state: state || null,
      postal_code: zip || null
    };
  }

  // Esponi funzioni globali richieste dal submit del form
  window.setupGeoapifyAutocomplete = setupGeoapifyAutocomplete;
  window.buildAddressFromForm = buildAddressFromForm;
})();