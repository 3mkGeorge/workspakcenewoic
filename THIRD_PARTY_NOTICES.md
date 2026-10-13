# Third-party components

The application vendors these frontend assets for offline use. Corresponding license texts are included beside them in `static/vendor/`.

| Component | Version | Source | License |
|---|---|---|---|
| Bootstrap | 5.3.8 | https://github.com/twbs/bootstrap | MIT |
| Chart.js | 4.5.0 | https://github.com/chartjs/Chart.js | MIT |
| Lucide | 0.468.0 | https://github.com/lucide-icons/lucide | ISC / MIT portions, see bundled notice |
| JsBarcode | 3.12.1 | https://github.com/lindell/JsBarcode | MIT |
| Inter | Variable font | https://github.com/google/fonts/tree/main/ofl/inter | SIL Open Font License |
| Noto Sans Arabic | Variable font | https://github.com/google/fonts/tree/main/ofl/notosansarabic | SIL Open Font License |

Python runtime packages, their versions, and transitive dependencies are listed in `requirements-lock.txt`. Wheel archives include their package metadata and upstream licenses. The included wheel files target CPython 3.13 on Windows x64.

The ten optional demo product thumbnails are extracts of the screenshots supplied by the user for this project. They are used only by the explicitly invoked demo-data loader. Replace them with your own product photographs for real inventory.

No remote font, image, icon, analytics, or CDN service is contacted by the running application. The cube logo is a local SVG recreation made for this project.
