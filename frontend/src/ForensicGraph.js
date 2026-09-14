/**
 * ForensicGraph.js
 * Standalone, drop-in forensic money-trail visualization engine.
 * Supports: Continuous progressive edge trails, exact photon synchronization,
 * flow particles, sonar ripple waves, smooth lerp camera, and dual node styles (Circular / Cards).
 */

export class ForensicGraph {
    constructor(containerId, options = {}) {
        this.container = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
        if (!this.container) {
            throw new Error(`[ForensicGraph] Container '#${containerId}' not found.`);
        }

        // Ensure parent is styled for full containment
        const computedPosition = window.getComputedStyle(this.container).position;
        if (computedPosition === 'static') {
            this.container.style.position = 'relative';
        }

        // Main Canvas
        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;cursor:grab;z-index:1;display:block;';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        // Configuration
        this.nodeStyle = options.nodeStyle || 'circular'; // 'circular' | 'cards'
        this.showCurved = options.showCurved !== undefined ? options.showCurved : true;
        this.showBeams = options.showBeams !== undefined ? options.showBeams : true;
        this.playSpeed = options.playSpeed || 1.0;
        this.autoCamera = options.autoCamera !== undefined ? options.autoCamera : true;

        // Simulation State
        this.progress = 0.0;
        this.isPlaying = false;
        this.data = { nodes: [], edges: [] };
        this.particles = [];
        this.sonarWaves = [];
        this.totalParticles = 160;

        // Smooth Camera (Interpolated Dampened Lerp)
        this.camera = {
            x: 0,
            y: 0,
            targetX: 0,
            targetY: 0,
            scale: 1,
            targetScale: 1
        };

        // User Interaction, Node Dragging & View Lock
        this.isViewLocked = options.isViewLocked !== undefined ? options.isViewLocked : false;
        this.isDragging = false;
        this.dragStart = { x: 0, y: 0 };
        this.draggedNode = null;
        this.dragNodeOffset = { x: 0, y: 0 };
        this.hoveredNode = null;
        this.selectedNode = null;

        // Hooks / Callbacks
        this.onProgressUpdate = options.onProgressUpdate || null;
        this.onNodeSelect = options.onNodeSelect || null;
        this.onPhaseChange = options.onPhaseChange || null;

        this.lastTime = performance.now();
        this.initEvents();
        this.resize();

        // Auto resize listener
        this._resizeHandler = () => this.resize();
        window.addEventListener('resize', this._resizeHandler);
        if (typeof ResizeObserver !== 'undefined') {
            this._resizeObserver = new ResizeObserver(() => this.resize());
            this._resizeObserver.observe(this.container);
        }

        // Start render loop immediately
        this.start();
    }

    // --- Public API ---

    loadData(graphData) {
        this.data = JSON.parse(JSON.stringify(graphData));
        if (this.data.nodes && this.data.nodes.length > 0) {
            this.rearrange();
            this.selectedNode = this.data.nodes[0];
        }
        this.initParticles();
        this.updateCameraTarget(true);
    }

    setProgress(p) {
        this.progress = Math.max(0, Math.min(1, p));
        this.updateCameraTarget();
    }

    play() {
        if (this.progress >= 1.0) this.progress = 0.0;
        this.isPlaying = true;
    }

    pause() {
        this.isPlaying = false;
    }

    togglePlay() {
        if (this.isPlaying) this.pause();
        else this.play();
        return this.isPlaying;
    }

    setSpeed(speed) {
        this.playSpeed = Math.max(0.1, parseFloat(speed) || 1.0);
    }

    setNodeStyle(style) {
        if (style === 'circular' || style === 'cards') {
            this.nodeStyle = style;
            this.rearrange();
        }
    }

    setCurved(enabled) {
        this.showCurved = !!enabled;
    }

    setParticles(enabled) {
        this.showBeams = !!enabled;
    }

    setAutoCamera(enabled) {
        this.autoCamera = !!enabled;
        if (this.autoCamera) this.updateCameraTarget();
    }

    setViewLocked(locked) {
        this.isViewLocked = !!locked;
        if (this.isViewLocked) {
            this.recenter();
        }
        if (this.canvas) {
            this.canvas.style.cursor = this.isViewLocked ? 'default' : 'grab';
        }
    }

    toggleViewLock() {
        this.setViewLocked(!this.isViewLocked);
        return this.isViewLocked;
    }

    recenter() {
        this.autoCamera = true;
        this.camera.scale = 1;
        this.camera.targetScale = 1;
        this.updateCameraTarget(true);
    }

    /**
     * Professional Blockchain Forensic Hierarchical Force-Directed Layout Engine
     * Generates a DAG flow: Inbound Funders (Left) -> Investigated Target (Center) -> Mule Forward Hops -> VASP Exits (Right)
     * Features collision avoidance, generous spacing, edge-crossing minimization, and force relaxation.
     */
    computeForensicLayout(nodes, edges, nodeStyle = 'cards') {
        if (!nodes || nodes.length === 0) return { nodes: [], edges: edges || [] };

        const isCards = nodeStyle === 'cards';
        const cardW = isCards ? 200 : 80;
        const cardH = isCards ? 85 : 80;
        // Compact but readable spacing — enough clearance without spreading nodes off-screen
        const HORIZONTAL_LAYER_GAP = isCards ? 260 : 210;
        const VERTICAL_MIN_GAP = isCards ? 100 : 85;
        const BASE_Y = 280;

        const nodeMap = new Map();
        nodes.forEach(n => nodeMap.set(n.id, n));

        // 1. Identify Investigated Origin Target
        let rootNode = nodes.find(n => n.type === 'VICTIM' || n.node_type === 'ORIGIN_VICTIM' || n.hop === 0) || nodes[0];

        // 2. Build Adjacency Graphs
        const forwardAdj = new Map();
        const backwardAdj = new Map();
        nodes.forEach(n => {
            forwardAdj.set(n.id, []);
            backwardAdj.set(n.id, []);
        });

        edges.forEach(e => {
            if (forwardAdj.has(e.from)) forwardAdj.get(e.from).push(e.to);
            if (backwardAdj.has(e.to)) backwardAdj.get(e.to).push(e.from);
        });

        // 3. Assign Topological Flow Layers (-k for inbound funders, 0 for root, +k for forward hops)
        const layers = new Map();
        layers.set(rootNode.id, 0);

        // BFS Outward (Downstream hops: Layer +1, +2, +3...)
        const forwardQueue = [rootNode.id];
        const forwardVisited = new Set([rootNode.id]);
        while (forwardQueue.length > 0) {
            const currId = forwardQueue.shift();
            const currLayer = layers.get(currId) || 0;
            const neighbors = forwardAdj.get(currId) || [];
            neighbors.forEach(nxtId => {
                if (!forwardVisited.has(nxtId)) {
                    forwardVisited.add(nxtId);
                    layers.set(nxtId, currLayer + 1);
                    forwardQueue.push(nxtId);
                } else {
                    const existingL = layers.get(nxtId) || 0;
                    if (currLayer + 1 > existingL) {
                        layers.set(nxtId, currLayer + 1);
                    }
                }
            });
        }

        // BFS Inward (Upstream funding sources: Layer -1, -2...)
        const backwardQueue = [rootNode.id];
        const backwardVisited = new Set([rootNode.id]);
        while (backwardQueue.length > 0) {
            const currId = backwardQueue.shift();
            const currLayer = layers.get(currId) || 0;
            const sources = backwardAdj.get(currId) || [];
            sources.forEach(srcId => {
                if (!layers.has(srcId)) {
                    layers.set(srcId, currLayer - 1);
                    backwardVisited.add(srcId);
                    backwardQueue.push(srcId);
                }
            });
        }

        // Fallback for any unvisited nodes
        nodes.forEach(n => {
            if (!layers.has(n.id)) {
                const hopVal = typeof n.hop === 'number' ? n.hop : 1;
                layers.set(n.id, hopVal);
            }
        });

        // 4. Group Nodes by Layer
        const layerGroups = new Map();
        nodes.forEach(n => {
            const l = layers.get(n.id) ?? 0;
            if (!layerGroups.has(l)) layerGroups.set(l, []);
            layerGroups.get(l).push(n);
        });

        const sortedLayerKeys = Array.from(layerGroups.keys()).sort((a, b) => a - b);
        const minLayer = sortedLayerKeys[0] ?? 0;

        // 5. Initial Symmetrical Layer Placement with Median Sorting
        sortedLayerKeys.forEach(l => {
            const group = layerGroups.get(l);
            const count = group.length;

            // Sort nodes within each layer by connected neighbor mean Y to untangle edge crossings
            group.sort((a, b) => {
                const aConns = (backwardAdj.get(a.id) || []).concat(forwardAdj.get(a.id) || []);
                const bConns = (backwardAdj.get(b.id) || []).concat(forwardAdj.get(b.id) || []);
                const aMean = aConns.length > 0 ? aConns.reduce((s, cid) => s + (nodeMap.get(cid)?.y || BASE_Y), 0) / aConns.length : BASE_Y;
                const bMean = bConns.length > 0 ? bConns.reduce((s, cid) => s + (nodeMap.get(cid)?.y || BASE_Y), 0) / bConns.length : BASE_Y;
                return aMean - bMean;
            });

            group.forEach((node, idx) => {
                // Alternating curved vertical fanning
                const yOffset = (idx - (count - 1) / 2) * VERTICAL_MIN_GAP;
                node.x = (l - minLayer) * HORIZONTAL_LAYER_GAP + 180;
                node.y = BASE_Y + yOffset;
                node.layer = l;
            });
        });

        // 6. Force-Directed Physics Relaxation & Card Collision Avoidance (80 iterations)
        const iterations = 80;
        for (let iter = 0; iter < iterations; iter++) {
            const damping = Math.max(0.12, 1.0 - iter / iterations);

            // A. Node-to-Node Repulsion with Bounding Box Clearance
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const n1 = nodes[i];
                    const n2 = nodes[j];

                    const dx = n2.x - n1.x;
                    const dy = n2.y - n1.y;
                    const distSq = dx * dx + dy * dy || 1;
                    const dist = Math.sqrt(distSq);

                    // Clearance = half-width each + padding (smaller padding = tighter layout)
                    const minAllowedX = (n1.w || cardW) / 2 + (n2.w || cardW) / 2 + 30;
                    const minAllowedY = (n1.h || cardH) / 2 + (n2.h || cardH) / 2 + 28;

                    // Hard collision avoidance: only push nodes that actually overlap
                    if (Math.abs(dx) < minAllowedX && Math.abs(dy) < minAllowedY) {
                        const overlapY = minAllowedY - Math.abs(dy);
                        const pushY = (dy >= 0 ? 1 : -1) * Math.max(overlapY, 12) * 0.4 * damping;

                        if (n1.id !== rootNode.id) n1.y -= pushY;
                        if (n2.id !== rootNode.id) n2.y += pushY;
                    } else if (dist < 180) {
                        // Soft repulsion only within 180px — prevents excessive spreading
                        const force = ((180 - dist) / 180) * 8 * damping;
                        const fx = (dx / dist) * force * 0.15;
                        const fy = (dy / dist) * force * 0.7;

                        if (n1.id !== rootNode.id) { n1.x -= fx; n1.y -= fy; }
                        if (n2.id !== rootNode.id) { n2.x += fx; n2.y += fy; }
                    }
                }
            }

            // B. Connected Edge Spring Forces & Straight Forward Flow Direction
            edges.forEach(e => {
                const fromNode = nodeMap.get(e.from);
                const toNode = nodeMap.get(e.to);
                if (!fromNode || !toNode) return;

                const dy = toNode.y - fromNode.y;
                const springY = dy * 0.08 * damping;

                if (toNode.id !== rootNode.id) toNode.y -= springY * 0.5;
                if (fromNode.id !== rootNode.id) fromNode.y += springY * 0.5;

                // Enforce directional left-to-right flow spacing (reduced to prevent over-spreading)
                const minEdgeDx = isCards ? 200 : 160;
                if (toNode.x < fromNode.x + minEdgeDx) {
                    if (toNode.id !== rootNode.id) toNode.x += (fromNode.x + minEdgeDx - toNode.x) * 0.25 * damping;
                }
            });

            // C. Layer Vertical Centering Anchor
            sortedLayerKeys.forEach(l => {
                const group = layerGroups.get(l);
                if (!group || group.length === 0) return;
                const groupCenterY = group.reduce((sum, n) => sum + n.y, 0) / group.length;
                // Stronger center-pull keeps all layers vertically centered → compact layout
                const centerPull = (BASE_Y - groupCenterY) * 0.10 * damping;
                group.forEach(n => {
                    if (n.id !== rootNode.id) n.y += centerPull;
                });
            });
        }

        return { nodes, edges };
    }

    rearrange() {
        if (!this.data.nodes || this.data.nodes.length === 0) return;

        const layoutResult = this.computeForensicLayout(this.data.nodes, this.data.edges, this.nodeStyle);
        this.data.nodes = layoutResult.nodes;

        // Auto Frame & Recenter
        this.autoCamera = true;
        this.camera.scale = 1;
        this.camera.targetScale = 1;
        this.updateCameraTarget(true);
    }

    resize() {
        const rect = this.container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = Math.round(rect.width * dpr);
        this.canvas.height = Math.round(rect.height * dpr);
        this.ctx.setTransform(1, 0, 0, 1, 0, 0); // reset transform
        this.ctx.scale(dpr, dpr);

        this.updateCameraTarget();
    }

    destroy() {
        this.isPlaying = false;
        window.removeEventListener('resize', this._resizeHandler);
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        if (this.canvas && this.canvas.parentNode) {
            this.canvas.parentNode.removeChild(this.canvas);
        }
    }

    // --- Particle & Sonar Mechanics ---

    initParticles() {
        this.particles = [];
        if (!this.data.edges || this.data.edges.length === 0) return;

        for (let i = 0; i < this.totalParticles; i++) {
            const edge = this.data.edges[i % this.data.edges.length];
            this.particles.push({
                edgeId: edge.id,
                t: Math.random(),
                speed: 0.0035 + Math.random() * 0.005,
                size: 1.6 + Math.random() * 2.0,
                color: edge.amount >= 5000 ? '#f59e0b' : '#38bdf8'
            });
        }
    }

    triggerSonar(x, y, color) {
        this.sonarWaves.push({
            x,
            y,
            radius: 14,
            maxRadius: 75,
            opacity: 0.85,
            color: color || '#f59e0b'
        });
    }

    // --- Geometry Helpers ---

    getBezierControlPoints(x1, y1, x2, y2, curvature = 0, isCurved = true) {
        const dx = x2 - x1;
        const dy = y2 - y1;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;

        // Straight Lines Mode
        if (!isCurved) {
            return {
                cp1: { x: x1 + dx * 0.33, y: y1 + dy * 0.33 },
                cp2: { x: x1 + dx * 0.67, y: y1 + dy * 0.67 }
            };
        }

        // True Cubic Bezier Curves Mode
        const effCurvature = curvature && curvature !== 0 ? curvature : 0.22;
        const arc = Math.max(30, Math.min(85, dist * effCurvature));

        if (dx >= 0) {
            if (dy < -15) {
                // Smooth upward S-curve transition
                return {
                    cp1: { x: x1 + dx * 0.45, y: y1 - arc * 0.35 },
                    cp2: { x: x2 - dx * 0.45, y: y2 + arc * 0.15 }
                };
            } else if (dy > 15) {
                // Smooth downward S-curve transition
                return {
                    cp1: { x: x1 + dx * 0.45, y: y1 + arc * 0.35 },
                    cp2: { x: x2 - dx * 0.45, y: y2 - arc * 0.15 }
                };
            } else {
                // Level edge: distinctive, elegant upward Bezier arc
                return {
                    cp1: { x: x1 + dx * 0.35, y: y1 - arc },
                    cp2: { x: x2 - dx * 0.35, y: y2 - arc }
                };
            }
        } else {
            // Backward loop (if node dragged behind upstream nodes)
            const loopOffset = Math.max(60, arc);
            return {
                cp1: { x: x1 + 60, y: y1 - loopOffset },
                cp2: { x: x2 - 60, y: y2 - loopOffset }
            };
        }
    }

    getPointOnCubicCurve(p0, cp1, cp2, p1, t) {
        const inv = 1 - t;
        const inv2 = inv * inv;
        const inv3 = inv2 * inv;
        const t2 = t * t;
        const t3 = t2 * t;

        return {
            x: inv3 * p0.x + 3 * inv2 * t * cp1.x + 3 * inv * t2 * cp2.x + t3 * p1.x,
            y: inv3 * p0.y + 3 * inv2 * t * cp1.y + 3 * inv * t2 * cp2.y + t3 * p1.y
        };
    }

    getNodeAnchors(fromNode, toNode, curvature, isCurved, style) {
        if (style === 'circular') {
            const rFrom = fromNode.radius || 26;
            const rTo = toNode.radius || 26;

            if (toNode.x > fromNode.x + 20) {
                // Clean horizontal port exit/entry
                return {
                    startPt: { x: fromNode.x + rFrom, y: fromNode.y },
                    endPt:   { x: toNode.x - rTo,     y: toNode.y }
                };
            } else {
                const angle = Math.atan2(toNode.y - fromNode.y, toNode.x - fromNode.x);
                return {
                    startPt: {
                        x: fromNode.x + Math.cos(angle) * rFrom,
                        y: fromNode.y + Math.sin(angle) * rFrom
                    },
                    endPt: {
                        x: toNode.x - Math.cos(angle) * rTo,
                        y: toNode.y - Math.sin(angle) * rTo
                    }
                };
            }
        } else {
            // Forensic Cards (Horizontal dock ports)
            const wFrom = fromNode.w || 175;
            const wTo = toNode.w || 175;
            return {
                startPt: { x: fromNode.x + wFrom / 2, y: fromNode.y },
                endPt:   { x: toNode.x - wTo / 2,     y: toNode.y }
            };
        }
    }

    roundRect(ctx, x, y, width, height, radius) {
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.lineTo(x + width - radius, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        ctx.lineTo(x + width, y + height - radius);
        ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        ctx.lineTo(x + radius, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        ctx.lineTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.closePath();
    }

    hexToRgba(hex, alpha = 1) {
        if (!hex) return `rgba(56, 189, 248, ${alpha})`;
        if (hex.startsWith('rgba') || hex.startsWith('rgb')) return hex;
        let c = hex.replace('#', '');
        if (c.length === 3) c = c.split('').map(x => x + x).join('');
        const num = parseInt(c, 16);
        if (isNaN(num)) return `rgba(56, 189, 248, ${alpha})`;
        const r = (num >> 16) & 255;
        const g = (num >> 8) & 255;
        const b = num & 255;
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    // --- Dynamic Bounding Box Camera Management ---

    updateCameraTarget(instant = false) {
        if (!this.autoCamera || !this.data.nodes || this.data.nodes.length === 0) return;
        const rect = this.container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        this.data.nodes.forEach(n => {
            const padX = this.nodeStyle === 'cards' ? (n.w || 180) / 2 + 24 : (n.radius || 30) + 28;
            const padY = this.nodeStyle === 'cards' ? (n.h || 70) / 2 + 24 : (n.radius || 30) + 32;
            minX = Math.min(minX, n.x - padX);
            maxX = Math.max(maxX, n.x + padX);
            minY = Math.min(minY, n.y - padY);
            maxY = Math.max(maxY, n.y + padY);
        });

        const graphW = Math.max(maxX - minX, 300);
        const graphH = Math.max(maxY - minY, 200);
        const graphCenterX = (minX + maxX) / 2;
        const graphCenterY = (minY + maxY) / 2;

        // Leave a 60px margin on each side so nodes never kiss the edge
        const scaleX = (rect.width - 120) / graphW;
        const scaleY = (rect.height - 120) / graphH;
        // Cap at 0.85 — never zoom in beyond natural size; always fit full graph
        const fitScale = Math.min(0.85, Math.max(0.25, Math.min(scaleX, scaleY)));

        this.camera.targetScale = fitScale;

        if (this.isPlaying && this.progress > 0 && this.progress < 1) {
            // Track the active flow frontier smoothly along X
            const flowX = minX + (maxX - minX) * this.progress;
            this.camera.targetX = rect.width / 2 - flowX * this.camera.targetScale;
            this.camera.targetY = rect.height / 2 - graphCenterY * this.camera.targetScale;
        } else {
            // Center the entire graph perfectly in viewport
            this.camera.targetX = rect.width / 2 - graphCenterX * this.camera.targetScale;
            this.camera.targetY = rect.height / 2 - graphCenterY * this.camera.targetScale;
        }

        if (instant) {
            this.camera.x = this.camera.targetX;
            this.camera.y = this.camera.targetY;
            this.camera.scale = this.camera.targetScale;
        }
    }

    // --- Rendering Modules ---

    drawCircularNode(ctx, node, isDiscovered, isActive, isHovered) {
        const { x, y, radius = 26, label, sub, amount, color = '#f59e0b', type } = node;

        ctx.save();
        if (isActive || isHovered) {
            ctx.shadowColor = color;
            ctx.shadowBlur = 24;
        }

        if (isActive) {
            ctx.beginPath();
            ctx.arc(x, y, radius + 8, 0, Math.PI * 2);
            ctx.fillStyle = this.hexToRgba(color, 0.22);
            ctx.fill();
        }

        // Outer boundary ring
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = isDiscovered ? '#0b111e' : '#080c14';
        ctx.strokeStyle = isDiscovered ? (isActive ? '#ffffff' : color) : this.hexToRgba(color, 0.45);
        ctx.lineWidth = isActive ? 3 : 2;
        ctx.fill();
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Core accent bead
        ctx.beginPath();
        ctx.arc(x, y, radius * 0.38, 0, Math.PI * 2);
        ctx.fillStyle = isDiscovered ? color : this.hexToRgba(color, 0.45);
        ctx.fill();

        // Floating Badge Pill (Top)
        const unitText = node.unit || node.asset || (node.chain === 'TRON' ? 'TRX' : 'USDT');
        const topText = type === 'VASP' ? `VASP: ${amount.toLocaleString()} ${unitText}` : (type === 'VICTIM' ? 'REPORTED WALLET' : type);
        ctx.font = '700 9px "JetBrains Mono", monospace';
        const tbw = ctx.measureText(topText).width + 12;
        const tbh = 18;
        const tbx = x - tbw / 2;
        const tby = y - radius - tbh - 8;

        ctx.fillStyle = isDiscovered ? this.hexToRgba(color, 0.18) : this.hexToRgba(color, 0.10);
        ctx.strokeStyle = isDiscovered ? color : this.hexToRgba(color, 0.35);
        ctx.lineWidth = 1;
        this.roundRect(ctx, tbx, tby, tbw, tbh, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = isDiscovered ? color : this.hexToRgba(color, 0.75);
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(topText, x, tby + tbh / 2);

        // Typography (Bottom)
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.font = '700 12px "Inter", sans-serif';
        ctx.fillStyle = isDiscovered ? '#f8fafc' : '#94a3b8';
        ctx.fillText(label, x, y + radius + 8);

        ctx.font = '500 10px "JetBrains Mono", monospace';
        ctx.fillStyle = isDiscovered ? '#94a3b8' : '#64748b';
        ctx.fillText(sub, x, y + radius + 24);

        ctx.restore();
    }

    drawForensicCard(ctx, node, isDiscovered, isActive, isHovered) {
        const { x, y, label, sub, type, amount, color = '#38bdf8', riskScore } = node;
        const w = node.w || 180;
        const h = node.h || 70;
        const left = x - w / 2;
        const top = y - h / 2;
        const radius = 9;
        const isTarget = type === 'VICTIM' || node.node_type === 'ORIGIN_VICTIM';

        ctx.save();

        // Extra Outer Target Halo for Investigated Starting Wallet
        if (isTarget) {
            ctx.strokeStyle = 'rgba(6, 182, 212, 0.75)';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 4]);
            this.roundRect(ctx, left - 6, top - 6, w + 12, h + 12, radius + 4);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // 1. Ambient Glow / Halo
        if (isActive) {
            ctx.shadowColor = color;
            ctx.shadowBlur = 28;
        } else if (isHovered) {
            ctx.shadowColor = color;
            ctx.shadowBlur = 20;
        } else if (isTarget) {
            ctx.shadowColor = '#06b6d4';
            ctx.shadowBlur = 22;
        } else if (isDiscovered) {
            ctx.shadowColor = this.hexToRgba(color, 0.35);
            ctx.shadowBlur = 12;
        } else {
            ctx.shadowBlur = 0;
        }

        // 2. High-Tech Gradient Surface (Entity-Tuned Luminescence)
        const bgGrad = ctx.createLinearGradient(left, top, left, top + h);
        if (isTarget) {
            bgGrad.addColorStop(0, 'rgba(6, 182, 212, 0.28)');
            bgGrad.addColorStop(0.35, 'rgba(10, 25, 45, 0.98)');
            bgGrad.addColorStop(1, 'rgba(8, 14, 28, 0.98)');
        } else if (isDiscovered) {
            bgGrad.addColorStop(0, this.hexToRgba(color, 0.22));
            bgGrad.addColorStop(0.35, 'rgba(17, 24, 39, 0.95)');
            bgGrad.addColorStop(1, 'rgba(10, 14, 26, 0.98)');
        } else {
            bgGrad.addColorStop(0, this.hexToRgba(color, 0.10));
            bgGrad.addColorStop(0.4, 'rgba(17, 24, 39, 0.75)');
            bgGrad.addColorStop(1, 'rgba(10, 14, 22, 0.88)');
        }
        ctx.fillStyle = bgGrad;

        // 3. Beveled Gradient Border
        const borderGrad = ctx.createLinearGradient(left, top, left + w, top + h);
        if (isTarget) {
            borderGrad.addColorStop(0, '#ffffff');
            borderGrad.addColorStop(0.4, '#06b6d4');
            borderGrad.addColorStop(1, '#0891b2');
        } else if (isDiscovered) {
            borderGrad.addColorStop(0, isActive ? '#ffffff' : this.hexToRgba(color, 0.95));
            borderGrad.addColorStop(0.45, this.hexToRgba(color, 0.55));
            borderGrad.addColorStop(1, this.hexToRgba(color, 0.22));
        } else {
            borderGrad.addColorStop(0, this.hexToRgba(color, 0.50));
            borderGrad.addColorStop(0.5, 'rgba(51, 65, 85, 0.35)');
            borderGrad.addColorStop(1, 'rgba(30, 41, 59, 0.25)');
        }
        ctx.strokeStyle = borderGrad;
        ctx.lineWidth = isTarget ? 2.5 : (isActive ? 2.2 : (isHovered ? 1.8 : 1.25));

        this.roundRect(ctx, left, top, w, h, radius);
        ctx.fill();
        ctx.stroke();
        ctx.shadowBlur = 0; // Reset blur for crisp child elements

        // 4. Subtle Top-Left Ambient Light Cone
        const glowGrad = ctx.createRadialGradient(left + 15, top + 15, 2, left + 15, top + 15, w * 0.7);
        glowGrad.addColorStop(0, isDiscovered ? this.hexToRgba(color, 0.18) : this.hexToRgba(color, 0.08));
        glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = glowGrad;
        this.roundRect(ctx, left, top, w, h, radius);
        ctx.fill();

        // 5. Sleek Neon Accent Indicator Strip (Left)
        const barX = left + 6;
        const barY = top + 10;
        const barW = 3.5;
        const barH = h - 20;
        const barR = 1.75;

        const barGrad = ctx.createLinearGradient(barX, barY, barX, barY + barH);
        if (isTarget) {
            barGrad.addColorStop(0, '#ffffff');
            barGrad.addColorStop(0.3, '#06b6d4');
            barGrad.addColorStop(1, '#0891b2');
        } else if (isDiscovered) {
            barGrad.addColorStop(0, '#ffffff');
            barGrad.addColorStop(0.3, color);
            barGrad.addColorStop(1, this.hexToRgba(color, 0.45));
        } else {
            barGrad.addColorStop(0, this.hexToRgba(color, 0.75));
            barGrad.addColorStop(1, this.hexToRgba(color, 0.30));
        }
        ctx.fillStyle = barGrad;
        this.roundRect(ctx, barX, barY, barW, barH, barR);
        ctx.fill();

        // 6. Category Capsule Badge (Top Right)
        ctx.font = '700 8.5px "JetBrains Mono", monospace';
        const badgeText = isTarget ? '🎯 TARGET' : (type || 'NODE');
        const badgeW = ctx.measureText(badgeText).width + 12;
        const badgeH = 16;
        const badgeX = left + w - badgeW - 7;
        const badgeY = top + 7;

        ctx.fillStyle = isTarget ? 'rgba(6, 182, 212, 0.22)' : (isDiscovered ? this.hexToRgba(color, 0.18) : this.hexToRgba(color, 0.10));
        ctx.strokeStyle = isTarget ? '#06b6d4' : (isDiscovered ? this.hexToRgba(color, 0.6) : this.hexToRgba(color, 0.40));
        ctx.lineWidth = 1;
        this.roundRect(ctx, badgeX, badgeY, badgeW, badgeH, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = isTarget ? '#38bdf8' : (isDiscovered ? color : this.hexToRgba(color, 0.85));
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(badgeText, badgeX + badgeW / 2, badgeY + badgeH / 2);

        // 7. Entity Label (Top Left)
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.font = '700 12px "Inter", -apple-system, sans-serif';
        ctx.fillStyle = isDiscovered ? '#f8fafc' : '#cbd5e1';
        ctx.fillText(label, left + 16, top + 9);

        // 8. Address Subtext
        ctx.font = '500 9.5px "JetBrains Mono", monospace';
        ctx.fillStyle = isDiscovered ? '#94a3b8' : '#64748b';
        ctx.fillText(sub, left + 16, top + 26);

        // 9. Live Real Token Amount Display
        const tokenUnit = node.unit || node.asset || node.token_symbol || (node.chain === 'TRON' ? 'TRX' : 'USDT');
        ctx.font = '700 11.5px "JetBrains Mono", monospace';
        if (isDiscovered) {
            ctx.fillStyle = '#ffffff';
            ctx.fillText(`${amount.toLocaleString()}`, left + 16, top + 47);
            const amtW = ctx.measureText(`${amount.toLocaleString()}`).width;
            ctx.font = '700 9px "JetBrains Mono", monospace';
            ctx.fillStyle = this.hexToRgba(color, 0.95);
            ctx.fillText(` ${tokenUnit}`, left + 16 + amtW, top + 49);
        } else {
            ctx.fillStyle = '#94a3b8';
            ctx.fillText(`${amount.toLocaleString()} ${tokenUnit}`, left + 16, top + 47);
        }

        // 10. Risk Score Capsule (Bottom Right)
        if (isDiscovered && riskScore !== undefined && riskScore > 0) {
            const riskColor = riskScore > 75 ? '#f43f5e' : (riskScore > 30 ? '#f59e0b' : '#10b981');
            const riskText = `RISK ${riskScore}`;
            ctx.font = '700 8.5px "JetBrains Mono", monospace';
            const rw = ctx.measureText(riskText).width + 16;
            const rh = 15;
            const rx = left + w - rw - 7;
            const ry = top + h - rh - 7;

            ctx.fillStyle = this.hexToRgba(riskColor, 0.16);
            ctx.strokeStyle = this.hexToRgba(riskColor, 0.55);
            ctx.lineWidth = 1;
            this.roundRect(ctx, rx, ry, rw, rh, 4);
            ctx.fill();
            ctx.stroke();

            // Status Indicator Dot inside Risk Badge
            ctx.beginPath();
            ctx.arc(rx + 5.5, ry + rh / 2, 2.5, 0, Math.PI * 2);
            ctx.fillStyle = riskColor;
            ctx.fill();

            // Risk Text
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = riskColor;
            ctx.fillText(riskText, rx + 11, ry + rh / 2);
        }

        ctx.restore();
    }

    // --- Main Render Engine ---

    start() {
        const loop = (time) => {
            const dt = Math.min((time - this.lastTime) / 1000, 0.1);
            this.lastTime = time;

            if (this.isPlaying) {
                this.progress += 0.075 * this.playSpeed * dt;
                if (this.progress > 1.0) {
                    this.progress = 1.0;
                    this.isPlaying = false;
                }
                if (this.onProgressUpdate) {
                    this.onProgressUpdate(this.progress);
                }
                this.updateCameraTarget();
            }

            this.render(dt);
            requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
    }

    render(dt) {
        const rect = this.container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        const dpr = window.devicePixelRatio || 1;
        const targetWidth = Math.round(rect.width * dpr);
        const targetHeight = Math.round(rect.height * dpr);

        // Keep canvas buffer synchronized with physical display pixels dynamically
        if (this.canvas.width !== targetWidth || this.canvas.height !== targetHeight) {
            this.canvas.width = targetWidth;
            this.canvas.height = targetHeight;
        }

        // Unconditionally reset transform, shadow, alpha and clear full physical backbuffer
        this.ctx.setTransform(1, 0, 0, 1, 0, 0);
        this.ctx.shadowBlur = 0;
        this.ctx.shadowColor = 'transparent';
        this.ctx.globalAlpha = 1.0;
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Scale by device pixel ratio for CSS coordinate space
        this.ctx.scale(dpr, dpr);

        // Camera Interpolation (Dampened Lerp)
        const lerpSpeed = 0.08;
        this.camera.x += (this.camera.targetX - this.camera.x) * lerpSpeed;
        this.camera.y += (this.camera.targetY - this.camera.y) * lerpSpeed;
        this.camera.scale += (this.camera.targetScale - this.camera.scale) * lerpSpeed;

        this.ctx.save();
        try {
            this.ctx.translate(this.camera.x, this.camera.y);
            this.ctx.scale(this.camera.scale, this.camera.scale);

        // 1. Draw Edges with EXACT Trail-Dot Synchronization
        if (this.data.edges) {
            this.data.edges.forEach(edge => {
                const fromNode = this.data.nodes.find(n => n.id === edge.from);
                const toNode = this.data.nodes.find(n => n.id === edge.to);
                if (!fromNode || !toNode) return;

                const { startPt, endPt } = this.getNodeAnchors(fromNode, toNode, edge.curvature, this.showCurved, this.nodeStyle);
                const cp = this.getBezierControlPoints(startPt.x, startPt.y, endPt.x, endPt.y, edge.curvature, this.showCurved);

                let edgeProgress = 0;
                if (this.progress >= edge.endP) {
                    edgeProgress = 1;
                } else if (this.progress <= edge.startP) {
                    edgeProgress = 0;
                } else {
                    edgeProgress = (this.progress - edge.startP) / (edge.endP - edge.startP);
                }

                // Inactive Base Path (Smooth Bezier or Direct Straight Line)
                this.ctx.beginPath();
                this.ctx.moveTo(startPt.x, startPt.y);
                if (this.showCurved) {
                    this.ctx.bezierCurveTo(cp.cp1.x, cp.cp1.y, cp.cp2.x, cp.cp2.y, endPt.x, endPt.y);
                } else {
                    this.ctx.lineTo(endPt.x, endPt.y);
                }
                this.ctx.strokeStyle = 'rgba(30, 41, 59, 0.65)';
                this.ctx.lineWidth = 1.8;
                this.ctx.setLineDash([3, 5]);
                this.ctx.stroke();
                this.ctx.setLineDash([]);

                const isFull = edgeProgress >= 1;
                const isHighVolume = edge.amount >= 5000;

                // Directional Arrowhead at Target Anchor
                const arrowLen = 9;
                const arrowWidth = 5;
                const targetTangent = this.showCurved
                    ? Math.atan2(endPt.y - cp.cp2.y, endPt.x - cp.cp2.x)
                    : Math.atan2(endPt.y - startPt.y, endPt.x - startPt.x);
                this.ctx.save();
                this.ctx.translate(endPt.x, endPt.y);
                this.ctx.rotate(targetTangent);
                this.ctx.beginPath();
                this.ctx.moveTo(0, 0);
                this.ctx.lineTo(-arrowLen, -arrowWidth);
                this.ctx.lineTo(-arrowLen + 2, 0);
                this.ctx.lineTo(-arrowLen, arrowWidth);
                this.ctx.closePath();
                this.ctx.fillStyle = isFull
                    ? (isHighVolume ? '#f59e0b' : '#38bdf8')
                    : 'rgba(71, 85, 105, 0.65)';
                if (isFull) {
                    this.ctx.shadowColor = isHighVolume ? '#f59e0b' : '#38bdf8';
                    this.ctx.shadowBlur = 8;
                }
                this.ctx.fill();
                this.ctx.restore();

                // Active Liquid Pipe
                if (edgeProgress > 0) {
                    this.ctx.beginPath();
                    this.ctx.moveTo(startPt.x, startPt.y);

                    const steps = Math.max(4, Math.ceil(45 * edgeProgress));
                    for (let s = 1; s <= steps; s++) {
                        const t = (s / steps) * edgeProgress;
                        const pt = this.showCurved
                            ? this.getPointOnCubicCurve(startPt, cp.cp1, cp.cp2, endPt, t)
                            : { x: startPt.x + (endPt.x - startPt.x) * t, y: startPt.y + (endPt.y - startPt.y) * t };
                        this.ctx.lineTo(pt.x, pt.y);
                    }

                    this.ctx.strokeStyle = isHighVolume ? '#f59e0b' : '#38bdf8';
                    this.ctx.lineWidth = isHighVolume ? 3.2 : 2.2;
                    this.ctx.shadowColor = isHighVolume ? 'rgba(245, 158, 11, 0.8)' : 'rgba(56, 189, 248, 0.7)';
                    this.ctx.shadowBlur = isFull ? 10 : 18;
                    this.ctx.stroke();
                    this.ctx.shadowBlur = 0;

                    // Leading Photon Dot: Exact match with tip of trail
                    if (!isFull) {
                        const headPt = this.showCurved
                            ? this.getPointOnCubicCurve(startPt, cp.cp1, cp.cp2, endPt, edgeProgress)
                            : { x: startPt.x + (endPt.x - startPt.x) * edgeProgress, y: startPt.y + (endPt.y - startPt.y) * edgeProgress };

                        this.ctx.beginPath();
                        this.ctx.arc(headPt.x, headPt.y, 8, 0, Math.PI * 2);
                        this.ctx.fillStyle = isHighVolume ? 'rgba(245, 158, 11, 0.35)' : 'rgba(56, 189, 248, 0.35)';
                        this.ctx.fill();

                        this.ctx.beginPath();
                        this.ctx.arc(headPt.x, headPt.y, 4.5, 0, Math.PI * 2);
                        this.ctx.fillStyle = '#ffffff';
                        this.ctx.shadowColor = isHighVolume ? '#f59e0b' : '#38bdf8';
                        this.ctx.shadowBlur = 14;
                        this.ctx.fill();
                        this.ctx.shadowBlur = 0;
                    }
                }

                // Amount Badge
                if (edgeProgress > 0.35) {
                    const mid = this.showCurved
                        ? this.getPointOnCubicCurve(startPt, cp.cp1, cp.cp2, endPt, 0.5)
                        : { x: (startPt.x + endPt.x) / 2, y: (startPt.y + endPt.y) / 2 };

                    this.ctx.save();
                    this.ctx.translate(mid.x, mid.y - 12);

                    const alpha = Math.min(1, (edgeProgress - 0.35) * 2.5);
                    this.ctx.globalAlpha = alpha;

                    const edgeUnit = edge.unit || edge.asset || edge.token || (edge.chain === 'TRON' ? 'TRX' : 'USDT');
                    const label = `${edge.amount.toLocaleString()} ${edgeUnit}`;
                    this.ctx.font = '600 10px "JetBrains Mono", monospace';
                    const tw = this.ctx.measureText(label).width;
                    const pw = tw + 16;
                    const ph = 20;

                    this.ctx.fillStyle = '#080c14';
                    this.ctx.strokeStyle = edge.amount >= 5000 ? '#f59e0b' : '#38bdf8';
                    this.ctx.lineWidth = 1;
                    this.roundRect(this.ctx, -pw / 2, -ph / 2, pw, ph, 5);
                    this.ctx.fill();
                    this.ctx.stroke();

                    this.ctx.fillStyle = '#ffffff';
                    this.ctx.textAlign = 'center';
                    this.ctx.textBaseline = 'middle';
                    this.ctx.fillText(label, 0, 0);

                    this.ctx.restore();
                    this.ctx.globalAlpha = 1.0;
                }
            });
        }

        // 2. Draw Flow Particles
        if (this.showBeams && this.data.edges) {
            this.particles.forEach(p => {
                const edge = this.data.edges.find(e => e.id === p.edgeId);
                if (!edge) return;

                let edgeProgress = 0;
                if (this.progress >= edge.endP) {
                    edgeProgress = 1;
                } else if (this.progress <= edge.startP) {
                    edgeProgress = 0;
                } else {
                    edgeProgress = (this.progress - edge.startP) / (edge.endP - edge.startP);
                }

                if (edgeProgress <= 0.06) return;

                p.t += p.speed * this.playSpeed;
                if (p.t > edgeProgress) p.t = 0;

                const fromNode = this.data.nodes.find(n => n.id === edge.from);
                const toNode = this.data.nodes.find(n => n.id === edge.to);
                if (!fromNode || !toNode) return;

                const { startPt, endPt } = this.getNodeAnchors(fromNode, toNode, edge.curvature, this.showCurved, this.nodeStyle);
                const cp = this.getBezierControlPoints(startPt.x, startPt.y, endPt.x, endPt.y, edge.curvature, this.showCurved);
                const pos = this.showCurved
                    ? this.getPointOnCubicCurve(startPt, cp.cp1, cp.cp2, endPt, p.t)
                    : { x: startPt.x + (endPt.x - startPt.x) * p.t, y: startPt.y + (endPt.y - startPt.y) * p.t };

                this.ctx.beginPath();
                this.ctx.arc(pos.x, pos.y, p.size, 0, Math.PI * 2);
                this.ctx.fillStyle = p.color;
                this.ctx.shadowColor = p.color;
                this.ctx.shadowBlur = 8;
                this.ctx.fill();
                this.ctx.shadowBlur = 0;
            });
        }

        // 3. Draw Sonar Waves
        for (let i = this.sonarWaves.length - 1; i >= 0; i--) {
            const w = this.sonarWaves[i];
            w.radius += 45 * dt * this.playSpeed;
            w.opacity -= 0.8 * dt * this.playSpeed;

            if (w.opacity <= 0 || w.radius >= w.maxRadius) {
                this.sonarWaves.splice(i, 1);
                continue;
            }

            this.ctx.beginPath();
            this.ctx.arc(w.x, w.y, w.radius, 0, Math.PI * 2);
            this.ctx.strokeStyle = w.color;
            this.ctx.lineWidth = 1.5;
            this.ctx.globalAlpha = Math.max(w.opacity, 0);
            this.ctx.shadowColor = w.color;
            this.ctx.shadowBlur = 12;
            this.ctx.stroke();
            this.ctx.globalAlpha = 1.0;
            this.ctx.shadowBlur = 0;
        }

        // 4. Draw Nodes
        if (this.data.nodes) {
            this.data.nodes.forEach(node => {
                const isDiscovered = this.progress >= node.activationProgress;
                const isActive = isDiscovered && this.progress < node.activationProgress + 0.16;
                const isHovered = this.hoveredNode?.id === node.id;

                if (isActive && Math.random() < 0.04) {
                    this.triggerSonar(node.x, node.y, node.color);
                }

                if (this.nodeStyle === 'circular') {
                    this.drawCircularNode(this.ctx, node, isDiscovered, isActive, isHovered);
                } else {
                    this.drawForensicCard(this.ctx, node, isDiscovered, isActive, isHovered);
                }
            });
        }

        } finally {
            this.ctx.restore();
        }
    }

    // --- Interaction Event Listeners ---

    getCanvasCoordinates(e) {
        const rect = this.canvas.getBoundingClientRect();
        const clientX = e.clientX !== undefined ? e.clientX : (e.touches && e.touches[0].clientX);
        const clientY = e.clientY !== undefined ? e.clientY : (e.touches && e.touches[0].clientY);
        return {
            x: (clientX - rect.left - this.camera.x) / this.camera.scale,
            y: (clientY - rect.top - this.camera.y) / this.camera.scale
        };
    }

    findNodeAt(pos) {
        if (!this.data.nodes) return null;
        return this.data.nodes.find(n => {
            if (this.nodeStyle === 'circular') {
                const r = (n.radius || 26) + 12;
                const dx = pos.x - n.x;
                const dy = pos.y - n.y;
                return dx * dx + dy * dy <= r * r;
            } else {
                const w = n.w || 175;
                const h = n.h || 68;
                return (
                    pos.x >= n.x - w / 2 &&
                    pos.x <= n.x + w / 2 &&
                    pos.y >= n.y - h / 2 &&
                    pos.y <= n.y + h / 2
                );
            }
        });
    }

    initEvents() {
        this.canvas.addEventListener('mousedown', e => {
            const pos = this.getCanvasCoordinates(e);
            const clicked = this.findNodeAt(pos);

            if (clicked) {
                // Dragging a specific node
                this.selectedNode = clicked;
                this.draggedNode = clicked;
                this.dragNodeOffset = { x: pos.x - clicked.x, y: pos.y - clicked.y };
                this.triggerSonar(clicked.x, clicked.y, clicked.color);
                if (this.onNodeSelect) this.onNodeSelect(clicked);
                this.canvas.style.cursor = 'grabbing';
            } else {
                // Dragging the camera background (only if view is NOT locked)
                if (!this.isViewLocked) {
                    this.isDragging = true;
                    this.autoCamera = false;
                    this.dragStart.x = e.clientX - this.camera.x;
                    this.dragStart.y = e.clientY - this.camera.y;
                    this.canvas.style.cursor = 'grabbing';
                }
            }
        });

        window.addEventListener('mousemove', e => {
            const pos = this.getCanvasCoordinates(e);
            this.hoveredNode = this.findNodeAt(pos);

            // Active node dragging: updates node position live and updates all connected edges immediately!
            if (this.draggedNode) {
                this.draggedNode.x = pos.x - this.dragNodeOffset.x;
                this.draggedNode.y = pos.y - this.dragNodeOffset.y;
                this.canvas.style.cursor = 'grabbing';
                return;
            }

            // Camera panning (if view unlocked)
            if (this.isDragging && !this.isViewLocked) {
                this.camera.targetX = e.clientX - this.dragStart.x;
                this.camera.targetY = e.clientY - this.dragStart.y;
                this.camera.x = this.camera.targetX;
                this.camera.y = this.camera.targetY;
                this.canvas.style.cursor = 'grabbing';
            } else {
                this.canvas.style.cursor = this.hoveredNode ? 'grab' : (this.isViewLocked ? 'default' : 'grab');
            }
        });

        window.addEventListener('mouseup', () => {
            this.isDragging = false;
            this.draggedNode = null;
            this.canvas.style.cursor = this.hoveredNode ? 'grab' : (this.isViewLocked ? 'default' : 'grab');
        });

        this.canvas.addEventListener('wheel', e => {
            if (this.isViewLocked) return; // Prevent zooming when view is locked
            e.preventDefault();
            this.autoCamera = false;

            const rect = this.canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
            const currentScale = this.camera.targetScale;
            const nextScale = Math.min(Math.max(currentScale * zoomFactor, 0.25), 3.0);

            // Compute mouse position in world space to zoom relative to cursor
            const worldX = (mouseX - this.camera.targetX) / currentScale;
            const worldY = (mouseY - this.camera.targetY) / currentScale;

            this.camera.targetScale = nextScale;
            this.camera.targetX = mouseX - worldX * nextScale;
            this.camera.targetY = mouseY - worldY * nextScale;
        }, { passive: false });

        // Touch Support for node dragging and camera pan
        this.canvas.addEventListener('touchstart', e => {
            if (e.touches.length === 1) {
                const pos = this.getCanvasCoordinates(e);
                const clicked = this.findNodeAt(pos);
                if (clicked) {
                    this.selectedNode = clicked;
                    this.draggedNode = clicked;
                    this.dragNodeOffset = { x: pos.x - clicked.x, y: pos.y - clicked.y };
                    this.triggerSonar(clicked.x, clicked.y, clicked.color);
                    if (this.onNodeSelect) this.onNodeSelect(clicked);
                } else if (!this.isViewLocked) {
                    this.isDragging = true;
                    this.autoCamera = false;
                    this.dragStart.x = e.touches[0].clientX - this.camera.x;
                    this.dragStart.y = e.touches[0].clientY - this.camera.y;
                }
            }
        });

        this.canvas.addEventListener('touchmove', e => {
            if (e.touches.length === 1) {
                const pos = this.getCanvasCoordinates(e);
                if (this.draggedNode) {
                    this.draggedNode.x = pos.x - this.dragNodeOffset.x;
                    this.draggedNode.y = pos.y - this.dragNodeOffset.y;
                } else if (this.isDragging && !this.isViewLocked) {
                    this.camera.targetX = e.touches[0].clientX - this.dragStart.x;
                    this.camera.targetY = e.touches[0].clientY - this.dragStart.y;
                    this.camera.x = this.camera.targetX;
                    this.camera.y = this.camera.targetY;
                }
            }
        });

        this.canvas.addEventListener('touchend', () => {
            this.isDragging = false;
            this.draggedNode = null;
        });
    }
}