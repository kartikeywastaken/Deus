/**
 * 3D Wireframe Globe in 3D Space using Three.js for Deus Hero Section.
 */

(function initHeroGlobe() {
  'use strict';

  // Support both element IDs for the globe mount point
  const mount = document.getElementById('hero-globe-wrap') || document.getElementById('hero-coin');
  if (!mount) return;

  // Clear mount element
  mount.replaceChildren();

  // Check if THREE is available
  if (typeof THREE === 'undefined') {
    // Fallback simple wireframe element if Three.js script fails to load
    const fallback = document.createElement('div');
    fallback.className = 'space-globe';
    mount.append(fallback);
    return;
  }

  // Set up dimensions
  const width = mount.clientWidth || 320;
  const height = mount.clientHeight || 320;

  // 1. Scene, Camera, Renderer
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, width / height, 1, 1000);
  camera.position.z = 400;

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  mount.appendChild(renderer.domElement);

  // 2. Main 3D Globe Group
  const globeGroup = new THREE.Group();
  scene.add(globeGroup);

  // Outer Wireframe Sphere
  const radius = 120;
  const sphereGeo = new THREE.IcosahedronGeometry(radius, 4);
  const sphereMat = new THREE.MeshBasicMaterial({
    color: 0x7a2e34,
    wireframe: true,
    transparent: true,
    opacity: 0.45
  });
  const sphereMesh = new THREE.Mesh(sphereGeo, sphereMat);
  globeGroup.add(sphereMesh);

  // Inner Core Density Grid
  const coreGeo = new THREE.IcosahedronGeometry(radius * 0.98, 2);
  const coreMat = new THREE.MeshBasicMaterial({
    color: 0x7a5c46,
    wireframe: true,
    transparent: true,
    opacity: 0.25
  });
  const coreMesh = new THREE.Mesh(coreGeo, coreMat);
  globeGroup.add(coreMesh);

  // Orbital Ring A
  const ringGeoA = new THREE.TorusGeometry(radius * 1.35, 1.2, 16, 100);
  const ringMatA = new THREE.MeshBasicMaterial({
    color: 0x7a2e34,
    wireframe: true,
    transparent: true,
    opacity: 0.50
  });
  const ringA = new THREE.Mesh(ringGeoA, ringMatA);
  ringA.rotation.x = Math.PI / 3;
  ringA.rotation.y = Math.PI / 6;
  globeGroup.add(ringA);

  // Orbital Ring B
  const ringGeoB = new THREE.TorusGeometry(radius * 1.5, 1, 16, 100);
  const ringMatB = new THREE.MeshBasicMaterial({
    color: 0x7a5c46,
    wireframe: true,
    transparent: true,
    opacity: 0.40
  });
  const ringB = new THREE.Mesh(ringGeoB, ringMatB);
  ringB.rotation.x = -Math.PI / 4;
  ringB.rotation.y = -Math.PI / 5;
  globeGroup.add(ringB);

  // Floating 3D Node Markers on Globe Surface
  const nodeCount = 18;
  const nodeGeo = new THREE.SphereGeometry(3.5, 12, 12);
  const nodeMat = new THREE.MeshBasicMaterial({ color: 0xeba36b });

  for (let i = 0; i < nodeCount; i++) {
    const nodeMesh = new THREE.Mesh(nodeGeo, nodeMat);
    const phi = Math.acos(-1 + (2 * i) / nodeCount);
    const theta = Math.sqrt(nodeCount * Math.PI) * phi;

    nodeMesh.position.x = radius * Math.cos(theta) * Math.sin(phi);
    nodeMesh.position.y = radius * Math.sin(theta) * Math.sin(phi);
    nodeMesh.position.z = radius * Math.cos(phi);

    globeGroup.add(nodeMesh);
  }

  // Mouse & Scroll interactivity
  let targetRotationX = 0;
  let targetRotationY = 0;

  function onMouseMove(event) {
    const windowHalfX = window.innerWidth / 2;
    const windowHalfY = window.innerHeight / 2;
    targetRotationY = ((event.clientX - windowHalfX) / windowHalfX) * 0.4;
    targetRotationX = ((event.clientY - windowHalfY) / windowHalfY) * 0.4;
  }

  window.addEventListener('mousemove', onMouseMove, { passive: true });

  // 3. Animation Loop
  function animate() {
    requestAnimationFrame(animate);

    // Continuous 3D rotation
    sphereMesh.rotation.y += 0.003;
    coreMesh.rotation.y -= 0.002;
    ringA.rotation.z += 0.004;
    ringB.rotation.z -= 0.003;

    // Smooth inertia tilt towards mouse
    globeGroup.rotation.y += (targetRotationY - globeGroup.rotation.y) * 0.05;
    globeGroup.rotation.x += (targetRotationX - globeGroup.rotation.x) * 0.05;

    // Render 3D Scene
    renderer.render(scene, camera);
  }

  animate();

  // Responsive Canvas Resize
  window.addEventListener('resize', () => {
    const newW = mount.clientWidth || 320;
    const newH = mount.clientHeight || 320;
    camera.aspect = newW / newH;
    camera.updateProjectionMatrix();
    renderer.setSize(newW, newH);
  });
})();
