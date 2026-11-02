/**
 * Smart Emergency Drone Delivery System - Interactive Simulation & Map Controller
 *
 * Strict Simulation-Only Notice:
 * This software models theoretical flight kinematics, waypoint interpolation,
 * and battery discharge profiles for academic dispatch analysis. It does NOT
 * send hardware control signals or interface with live UAV autopilots.
 */

(function () {
  'use strict';

  // CSRF helper
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  // Haversine distance in kilometres
  function haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371.0;
    const toRad = Math.PI / 180.0;
    const dLat = (lat2 - lat1) * toRad;
    const dLon = (lon2 - lon1) * toRad;
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  // Compass bearing in degrees [0, 360)
  function computeBearing(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180.0;
    const phi1 = lat1 * toRad;
    const phi2 = lat2 * toRad;
    const dLon = (lon2 - lon1) * toRad;
    const y = Math.sin(dLon) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) -
              Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
    let bearing = (Math.atan2(y, x) * 180.0) / Math.PI;
    return (bearing + 360.0) % 360.0;
  }

  // Format seconds into MM:SS or HH:MM:SS
  function formatTime(seconds) {
    if (isNaN(seconds) || seconds < 0) return '00:00';
    const s = Math.round(seconds);
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    const mm = String(mins).padStart(2, '0');
    const ss = String(secs).padStart(2, '0');
    return `${mm}:${ss}`;
  }

  class DroneSimulationApp {
    constructor(config) {
      this.simId = config.simulationId;
      this.initialState = config.initialState;
      this.isController = config.isController;

      this.map = null;
      this.droneMarker = null;
      this.selectedRouteLine = null;
      this.alternativeLines = [];

      this.waypoints = [];
      this.cumDistances = [];
      this.totalDistKm = 0;

      this.status = this.initialState.status || 'CREATED';
      this.progressPct = this.initialState.progress_percent || 0.0;
      this.distanceCoveredKm = this.initialState.telemetry.distance_covered_km || 0.0;
      this.elapsedSimSec = this.initialState.telemetry.elapsed_sim_seconds || 0.0;
      this.speedMultiplier = this.initialState.telemetry.speed_multiplier || 1.0;

      this.drone = this.initialState.drone || {};
      this.cruiseSpeedKmh = parseFloat(this.drone.cruise_speed_kmh) || 60.0;
      this.batteryCapacityWh = parseFloat(this.drone.battery_capacity_wh) || 850.0;
      this.currentBatteryWh = this.initialState.telemetry.current_battery_wh !== null
        ? parseFloat(this.initialState.telemetry.current_battery_wh)
        : this.batteryCapacityWh;
      this.estTotalEnergyWh = parseFloat(this.initialState.selected_route.estimated_energy_wh) || 70.0;

      this.animInterval = null;
      this.syncCounter = 0;
      this.lastTickTime = performance.now();

      this.initMetrics();
      this.initMap();
      this.bindUiEvents();
      this.updateUiDisplay();

      // If page refreshed while running, resume simulation loop smoothly
      if (this.status === 'RUNNING' && this.isController) {
        this.startKinematicsLoop();
      }
    }

    initMetrics() {
      const rawWps = this.initialState.selected_route.waypoints || [];
      this.waypoints = rawWps.map(w => ({
        lat: parseFloat(w.latitude),
        lon: parseFloat(w.longitude),
        alt: parseFloat(w.altitude_m || 50.0),
      }));

      if (this.waypoints.length < 2) return;

      this.cumDistances = [0.0];
      let total = 0.0;
      for (let i = 0; i < this.waypoints.length - 1; i++) {
        const d = haversineKm(
          this.waypoints[i].lat, this.waypoints[i].lon,
          this.waypoints[i + 1].lat, this.waypoints[i + 1].lon
        );
        total += d;
        this.cumDistances.push(total);
      }
      this.totalDistKm = total;
    }

    initMap() {
      const pickup = this.initialState.delivery_request.pickup;
      const dest = this.initialState.delivery_request.destination;

      const centerLat = (pickup.latitude + dest.latitude) / 2.0;
      const centerLon = (pickup.longitude + dest.longitude) / 2.0;

      // Initialize Leaflet Map
      this.map = L.map('simulation-map', {
        zoomControl: true,
        attributionControl: true,
      }).setView([centerLat, centerLon], 13);

      // OpenStreetMap Public Tile Layer
      const tileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
      }).addTo(this.map);

      // Graceful offline / network tile error handling
      const offlineNotice = document.getElementById('tile-offline-notice');
      tileLayer.on('tileerror', function () {
        if (offlineNotice) {
          offlineNotice.style.display = 'block';
        }
      });

      // Distinct, accessible custom markers
      const pickupIcon = L.divIcon({
        className: 'custom-pin-wrapper',
        html: '<div class="custom-pin pin-pickup" title="Pickup Origin">P</div>',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      });

      const destIcon = L.divIcon({
        className: 'custom-pin-wrapper',
        html: '<div class="custom-pin pin-dest" title="Delivery Destination">D</div>',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      });

      // Add Pickup & Destination Pins
      L.marker([pickup.latitude, pickup.longitude], { icon: pickupIcon })
        .addTo(this.map)
        .bindPopup(`<strong>Hospital Pickup Station</strong><br>Lat: ${pickup.latitude}<br>Lon: ${pickup.longitude}`);

      L.marker([dest.latitude, dest.longitude], { icon: destIcon })
        .addTo(this.map)
        .bindPopup(`<strong>Emergency Destination</strong><br>Lat: ${dest.latitude}<br>Lon: ${dest.longitude}<br>Priority: ${this.initialState.delivery_request.priority}`);

      // Render Alternative Routes (Amber/Slate Dashed Lines)
      const altRoutes = this.initialState.alternative_routes || [];
      altRoutes.forEach((alt, idx) => {
        const altPoints = (alt.waypoints || []).map(w => [parseFloat(w.latitude), parseFloat(w.longitude)]);
        if (altPoints.length >= 2) {
          const polyline = L.polyline(altPoints, {
            color: alt.feasibility_status === 'FEASIBLE' ? '#f59e0b' : '#94a3b8',
            weight: 3,
            opacity: 0.7,
            dashArray: '6, 8',
          }).addTo(this.map);

          polyline.bindPopup(
            `<strong>Candidate Corridor: ${alt.algorithm_name}</strong><br>` +
            `Distance: ${alt.estimated_distance_km} km<br>` +
            `Est. Duration: ${alt.estimated_duration_minutes} min<br>` +
            `Energy: ${alt.estimated_energy_wh} Wh<br>` +
            `Status: <span class="badge badge-${alt.feasibility_status.toLowerCase()}">${alt.feasibility_status}</span>` +
            (alt.rejection_reason ? `<br><small style="color:#ef4444">${alt.rejection_reason}</small>` : '')
          );
          this.alternativeLines.push(polyline);
        }
      });

      // Render Selected Route (Solid Electric Indigo Line)
      const selectedPoints = this.waypoints.map(w => [w.lat, w.lon]);
      if (selectedPoints.length >= 2) {
        this.selectedRouteLine = L.polyline(selectedPoints, {
          color: '#2563eb',
          weight: 4,
          opacity: 0.9,
          lineJoin: 'round',
        }).addTo(this.map);

        this.selectedRouteLine.bindPopup(
          `<strong>Selected Active Corridor: ${this.initialState.selected_route.algorithm_name}</strong><br>` +
          `Distance: ${this.initialState.selected_route.estimated_distance_km} km<br>` +
          `Est. Energy: ${this.estTotalEnergyWh} Wh`
        );
      }

      // Render Drone Marker
      const initialPos = this.interpolate(this.distanceCoveredKm);
      const droneIcon = L.divIcon({
        className: 'custom-drone-wrapper',
        html: `<div id="drone-icon-element" class="custom-drone-icon" style="transform: rotate(${initialPos.bearing}deg);">🚁</div>`,
        iconSize: [42, 42],
        iconAnchor: [21, 21],
      });

      this.droneMarker = L.marker([initialPos.lat, initialPos.lon], { icon: droneIcon, zIndexOffset: 1000 })
        .addTo(this.map)
        .bindPopup(`<strong>Simulated UAV: ${this.drone.drone_code || 'UNIT-01'}</strong><br>SIMULATION TELEMETRY ONLY`);

      // Fit map view to encompass all corridors
      const allBounds = L.latLngBounds([
        [pickup.latitude, pickup.longitude],
        [dest.latitude, dest.longitude],
        ...selectedPoints,
      ]);
      this.map.fitBounds(allBounds, { padding: [40, 40] });
    }

    interpolate(distanceKm) {
      if (!this.waypoints || this.waypoints.length === 0) {
        return { lat: 0, lon: 0, alt: 0, bearing: 0 };
      }

      const d = Math.max(0, Math.min(distanceKm, this.totalDistKm));

      if (d <= 1e-9 || this.waypoints.length === 1) {
        const w0 = this.waypoints[0];
        const w1 = this.waypoints[1] || w0;
        return {
          lat: w0.lat,
          lon: w0.lon,
          alt: w0.alt,
          bearing: computeBearing(w0.lat, w0.lon, w1.lat, w1.lon),
        };
      }

      if (d >= this.totalDistKm - 1e-9) {
        const wLast = this.waypoints[this.waypoints.length - 1];
        const wPrev = this.waypoints[this.waypoints.length - 2] || wLast;
        return {
          lat: wLast.lat,
          lon: wLast.lon,
          alt: wLast.alt,
          bearing: computeBearing(wPrev.lat, wPrev.lon, wLast.lat, wLast.lon),
        };
      }

      for (let i = 0; i < this.cumDistances.length - 1; i++) {
        const cStart = this.cumDistances[i];
        const cEnd = this.cumDistances[i + 1];
        if (cStart <= d && d <= cEnd) {
          const segLen = cEnd - cStart;
          const alpha = segLen > 1e-9 ? (d - cStart) / segLen : 0.0;
          const wStart = this.waypoints[i];
          const wEnd = this.waypoints[i + 1];

          const lat = wStart.lat + alpha * (wEnd.lat - wStart.lat);
          const lon = wStart.lon + alpha * (wEnd.lon - wStart.lon);
          const alt = wStart.alt + alpha * (wEnd.alt - wStart.alt);
          const bearing = computeBearing(wStart.lat, wStart.lon, wEnd.lat, wEnd.lon);

          return { lat, lon, alt, bearing };
        }
      }

      const wEnd = this.waypoints[this.waypoints.length - 1];
      return { lat: wEnd.lat, lon: wEnd.lon, alt: wEnd.alt, bearing: 0 };
    }

    bindUiEvents() {
      const btnStart = document.getElementById('btn-start-sim');
      const btnPause = document.getElementById('btn-pause-sim');
      const btnResume = document.getElementById('btn-resume-sim');
      const btnCancel = document.getElementById('btn-cancel-sim');

      if (btnStart) btnStart.addEventListener('click', () => this.handleStart());
      if (btnPause) btnPause.addEventListener('click', () => this.handlePause());
      if (btnResume) btnResume.addEventListener('click', () => this.handleResume());
      if (btnCancel) btnCancel.addEventListener('click', () => this.handleCancel());

      // Speed multipliers
      const speedBtns = document.querySelectorAll('.btn-speed');
      speedBtns.forEach(btn => {
        btn.addEventListener('click', e => {
          speedBtns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.speedMultiplier = parseFloat(btn.dataset.speed) || 1.0;
        });
      });
    }

    async handleStart() {
      if (!this.isController) return;
      try {
        const res = await fetch(`/simulation/api/${this.simId}/start`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
        });
        const data = await res.json();
        if (data.success) {
          this.status = 'RUNNING';
          this.startKinematicsLoop();
          this.updateUiDisplay();
        } else {
          alert('Could not start simulation: ' + data.error);
        }
      } catch (err) {
        console.error('Start error:', err);
      }
    }

    async handlePause() {
      if (!this.isController) return;
      try {
        const res = await fetch(`/simulation/api/${this.simId}/pause`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
        });
        const data = await res.json();
        if (data.success) {
          this.status = 'PAUSED';
          this.stopKinematicsLoop();
          this.updateUiDisplay();
          this.syncCheckpoint(true);
        } else {
          alert('Could not pause simulation: ' + data.error);
        }
      } catch (err) {
        console.error('Pause error:', err);
      }
    }

    async handleResume() {
      if (!this.isController) return;
      try {
        const res = await fetch(`/simulation/api/${this.simId}/resume`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
        });
        const data = await res.json();
        if (data.success) {
          this.status = 'RUNNING';
          this.startKinematicsLoop();
          this.updateUiDisplay();
        } else {
          alert('Could not resume simulation: ' + data.error);
        }
      } catch (err) {
        console.error('Resume error:', err);
      }
    }

    async handleCancel() {
      if (!this.isController) return;
      if (!confirm('Are you sure you want to cancel and abort this simulated mission?')) return;

      try {
        const res = await fetch(`/simulation/api/${this.simId}/cancel`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({ reason: 'Operator manual cancellation via cockpit' }),
        });
        const data = await res.json();
        if (data.success) {
          this.status = 'CANCELLED';
          this.stopKinematicsLoop();
          this.updateUiDisplay();
        } else {
          alert('Could not cancel simulation: ' + data.error);
        }
      } catch (err) {
        console.error('Cancel error:', err);
      }
    }

    startKinematicsLoop() {
      this.stopKinematicsLoop();
      this.lastTickTime = performance.now();
      // Tick every 100ms for smooth 60fps interpolation
      this.animInterval = setInterval(() => this.tick(), 100);
    }

    stopKinematicsLoop() {
      if (this.animInterval) {
        clearInterval(this.animInterval);
        this.animInterval = null;
      }
    }

    tick() {
      if (this.status !== 'RUNNING') {
        this.stopKinematicsLoop();
        return;
      }

      const now = performance.now();
      const dtSec = (now - this.lastTickTime) / 1000.0;
      this.lastTickTime = now;

      // Effective simulation seconds elapsed in this frame
      const simDt = dtSec * this.speedMultiplier;
      this.elapsedSimSec += simDt;

      // Distance advanced
      const deltaDist = (this.cruiseSpeedKmh / 3600.0) * simDt;
      this.distanceCoveredKm = Math.min(this.totalDistKm, this.distanceCoveredKm + deltaDist);
      this.progressPct = this.totalDistKm > 0 ? (this.distanceCoveredKm / this.totalDistKm) * 100.0 : 100.0;

      // Battery consumption model proxy
      const fractionCovered = this.totalDistKm > 0 ? (this.distanceCoveredKm / this.totalDistKm) : 1.0;
      const energyUsed = fractionCovered * this.estTotalEnergyWh;
      this.currentBatteryWh = Math.max(0.0, this.batteryCapacityWh - energyUsed);

      // Interpolate current position
      const pos = this.interpolate(this.distanceCoveredKm);

      // Update Leaflet marker position & heading
      if (this.droneMarker) {
        this.droneMarker.setLatLng([pos.lat, pos.lon]);
        const iconElem = document.getElementById('drone-icon-element');
        if (iconElem) {
          iconElem.style.transform = `rotate(${pos.bearing}deg)`;
        }
      }

      this.updateUiDisplay(pos);

      // Check if destination reached
      if (this.distanceCoveredKm >= this.totalDistKm - 1e-6 || this.progressPct >= 99.99) {
        this.handleCompletion(pos);
        return;
      }

      // Periodic state sync to avoid frequent DB writes (every ~1.5s = 15 ticks)
      this.syncCounter++;
      if (this.syncCounter >= 15) {
        this.syncCounter = 0;
        this.syncCheckpoint(false, pos);
      }
    }

    async handleCompletion(finalPos) {
      this.status = 'COMPLETED';
      this.progressPct = 100.0;
      this.stopKinematicsLoop();
      this.updateUiDisplay(finalPos);

      // Inform server to commit completion transaction & record AnalysisLog
      try {
        const res = await fetch(`/simulation/api/${this.simId}/step`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({
            delta_sim_seconds: 1.0,
            speed_multiplier: this.speedMultiplier,
          }),
        });
        const data = await res.json();
        if (data.success) {
          console.log('[+] Mission delivered and analysis log committed.');
        }
      } catch (err) {
        console.error('Completion sync error:', err);
      }
    }

    async syncCheckpoint(isImmediate = false, currentPos = null) {
      if (!this.isController) return;
      const pos = currentPos || this.interpolate(this.distanceCoveredKm);
      const remainingDist = Math.max(0.0, this.totalDistKm - this.distanceCoveredKm);

      try {
        await fetch(`/simulation/api/${this.simId}/checkpoint`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({
            progress_percent: this.progressPct,
            latitude: pos.lat,
            longitude: pos.lon,
            altitude_m: pos.alt,
            elapsed_seconds: this.elapsedSimSec,
            distance_covered_km: this.distanceCoveredKm,
            remaining_distance_km: remainingDist,
            current_battery_wh: this.currentBatteryWh,
            speed_multiplier: this.speedMultiplier,
            extra_data: {
              heading_deg: pos.bearing,
            },
          }),
        });
      } catch (err) {
        console.warn('Checkpoint sync warning:', err);
      }
    }

    updateUiDisplay(pos) {
      const currentPos = pos || this.interpolate(this.distanceCoveredKm);
      const remainingDist = Math.max(0.0, this.totalDistKm - this.distanceCoveredKm);
      const remainingSec = (remainingDist / this.cruiseSpeedKmh) * 3600.0;

      // Status badge
      const badge = document.getElementById('status-badge');
      if (badge) {
        badge.textContent = this.status;
        badge.className = `badge badge-${this.status.toLowerCase()}`;
      }

      // Progress bar & text
      const progressFill = document.getElementById('progress-bar-fill');
      const progressPctText = document.getElementById('progress-pct-text');
      if (progressFill) progressFill.style.width = `${this.progressPct.toFixed(1)}%`;
      if (progressPctText) progressPctText.textContent = `${this.progressPct.toFixed(1)}%`;

      // Distances
      const coveredText = document.getElementById('dist-covered-val');
      const remainingText = document.getElementById('dist-remaining-val');
      if (coveredText) coveredText.textContent = `${this.distanceCoveredKm.toFixed(2)} km`;
      if (remainingText) remainingText.textContent = `${remainingDist.toFixed(2)} km`;

      // Timers
      const timeElapsedText = document.getElementById('time-elapsed-val');
      const timeRemainingText = document.getElementById('time-remaining-val');
      if (timeElapsedText) timeElapsedText.textContent = formatTime(this.elapsedSimSec);
      if (timeRemainingText) timeRemainingText.textContent = formatTime(remainingSec);

      // Telemetry coordinates
      const latVal = document.getElementById('telemetry-lat');
      const lonVal = document.getElementById('telemetry-lon');
      const altVal = document.getElementById('telemetry-alt');
      const headingVal = document.getElementById('telemetry-heading');
      if (latVal) latVal.textContent = currentPos.lat.toFixed(6);
      if (lonVal) lonVal.textContent = currentPos.lon.toFixed(6);
      if (altVal) altVal.textContent = `${currentPos.alt.toFixed(1)} m`;
      if (headingVal) headingVal.textContent = `${currentPos.bearing.toFixed(1)}°`;

      // Battery level
      const batteryWhVal = document.getElementById('battery-wh-val');
      const batteryPctVal = document.getElementById('battery-pct-val');
      const batteryFill = document.getElementById('battery-bar-fill');
      const batteryPct = Math.max(0, Math.min(100, (this.currentBatteryWh / this.batteryCapacityWh) * 100.0));

      if (batteryWhVal) batteryWhVal.textContent = `${this.currentBatteryWh.toFixed(1)} Wh`;
      if (batteryPctVal) batteryPctVal.textContent = `${batteryPct.toFixed(1)}%`;
      if (batteryFill) {
        batteryFill.style.width = `${batteryPct}%`;
        if (batteryPct < 20) {
          batteryFill.style.backgroundColor = '#ef4444'; // Red
        } else if (batteryPct < 40) {
          batteryFill.style.backgroundColor = '#f59e0b'; // Amber
        } else {
          batteryFill.style.backgroundColor = '#10b981'; // Green
        }
      }

      // Button states
      const btnStart = document.getElementById('btn-start-sim');
      const btnPause = document.getElementById('btn-pause-sim');
      const btnResume = document.getElementById('btn-resume-sim');
      const btnCancel = document.getElementById('btn-cancel-sim');

      if (btnStart) btnStart.style.display = (this.status === 'CREATED' || this.status === 'PENDING') ? 'inline-block' : 'none';
      if (btnPause) btnPause.style.display = this.status === 'RUNNING' ? 'inline-block' : 'none';
      if (btnResume) btnResume.style.display = this.status === 'PAUSED' ? 'inline-block' : 'none';
      if (btnCancel) {
        btnCancel.disabled = (this.status === 'COMPLETED' || this.status === 'CANCELLED');
      }
    }
  }

  // Export to global namespace
  window.DroneSimulationApp = DroneSimulationApp;
})();
