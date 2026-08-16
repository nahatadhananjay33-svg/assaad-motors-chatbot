/* Assad Motors — standalone chat app configuration (Phase 11A).
   Every dealership-specific detail lives here. Change this file only —
   no need to touch app.js / style.css / index.html. */
window.DEALER_CONFIG = {
  name: "Assad Motors",
  tagline: "Premium Pre-Owned Cars",

  // Contact links (top-right header buttons)
  phone: "tel:+919029664381",
  whatsapp: "https://wa.me/919029664381",
  instagram: "https://www.instagram.com/assad_motors/",

  // Logo image URL. Leave null to show the initials placeholder.
  logo: null,

  // Welcome screen
  greeting: "Welcome to Assad Motors",
  subGreeting: "How can I help you today?",
  // Opening chips. These are the filters customers actually use, so each one is
  // worded exactly as it is sent to the bot — verified to return results against
  // the live inventory (Manual 131, Automatic 56, Petrol 89, CNG 23, Luxury 27,
  // Sunroof 2, 7-seater 33). "Sunroof cars" keeps the plural noun on purpose:
  // that is what marks it as a search rather than a question about one car.
  suggestions: [
    "Manual",
    "Automatic",
    "Petrol",
    "Cng cars",
    "Luxury cars",
    "Sunroof cars",
    "7 seater"
  ],

  inputPlaceholder: "Ask anything about our cars...",
  footer: "Powered by Assad Motors AI",

  // Backend /chat API base URL.
  //  - "" (empty)      → same origin as the page (production: chat.assadmotors.com behind Nginx)
  //  - full URL        → e.g. "http://localhost:8000"
  //  - auto (default)  → same host the page was opened from, port 8000
  //    (works on the laptop AND on phones opening the LAN IP)
  apiUrl: "http://" + (location.hostname || "localhost") + ":8000"
};
