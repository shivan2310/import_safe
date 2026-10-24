import './DeliveryJourney.css';

/** Decorative arrival sequence that plays once each time Home opens. */
export default function DeliveryJourney() {
  return <div className="delivery-journey" aria-hidden="true">
    <div className="delivery-road"><div /></div>
    <div className="delivery-drop">
      <svg className="delivery-canopy" viewBox="0 0 160 150" fill="none">
        <path d="M12 66a68 62 0 0 1 136 0c-12-12-24-12-35 0-12-12-23-12-34 0-11-12-22-12-33 0-12-12-23-12-34 0Z" fill="#dce5d0" stroke="#596e49" strokeWidth="2" />
        <path d="M46 66C46 31 61 6 80 4c19 2 33 27 33 62M80 4v62M12 66l51 76m-17-76 25 76m42-76-25 76m60-76-51 76" stroke="#849974" strokeWidth="1.5" />
      </svg>
      <svg className="delivery-parcel" viewBox="0 0 80 72" fill="none"><path d="m6 18 34-14 34 14-34 15Z" fill="#eddbb4" stroke="#776a4e" strokeWidth="1.7"/><path d="m6 18 34 15v34L6 52Z" fill="#d7bc8a" stroke="#776a4e" strokeWidth="1.7"/><path d="m40 33 34-15v34L40 67Z" fill="#e8cfa1" stroke="#776a4e" strokeWidth="1.7"/><path d="m27 9 34 15v14l-10 4V28L17 14" fill="#a9bc98"/><path d="m49 49 16-7m-16 13 10-4" stroke="#776a4e" strokeWidth="2"/></svg>
    </div>
    <div className="delivery-truck-position">
      <div className="delivery-truck-drive">
        <svg className="delivery-truck" viewBox="0 0 260 145" fill="none">
          <path d="M13 99V65l30-35h51v70" fill="#a9bc98" stroke="#596e49" strokeWidth="2"/><path d="m25 65 24-26h27v26Z" fill="#f9f6ed" stroke="#596e49" strokeWidth="2"/>
          <path d="M101 66h142v40H94V77" fill="#dce5d0" stroke="#596e49" strokeWidth="2"/><path d="M101 66h142" stroke="#596e49" strokeWidth="4"/><path d="M10 105h238v12H10Z" fill="#596e49"/><path d="M111 81h118M111 94h118" stroke="#a9bc98"/>
          <circle cx="52" cy="117" r="19" fill="#34432e"/><circle cx="52" cy="117" r="9" fill="#e2e8d5"/><circle cx="210" cy="117" r="19" fill="#34432e"/><circle cx="210" cy="117" r="9" fill="#e2e8d5"/>
          <path d="M13 86h10M80 76h7" stroke="#f9f6ed" strokeWidth="4" strokeLinecap="round"/>
          <g className="delivery-loaded-parcel"><path d="M151 31h48v35h-48Z" fill="#e8cfa1" stroke="#776a4e" strokeWidth="2"/><path d="M170 31h10v20h-10Z" fill="#a9bc98"/></g>
        </svg>
        <span className="delivery-truck-label">OUT FOR DELIVERY ↤</span>
      </div>
    </div>
  </div>;
}

