import { useEffect, useState } from 'react'
import './App.css'

const emptyProductForm = {
  sku: '',
  name: '',
  description: '',
  unit_price: '',
  is_active: true,
}

const emptyDealerForm = {
  code: '',
  name: '',
  email: '',
  phone: '',
  address: '',
  is_active: true,
}

const emptyOrderItem = {
  product_id: '',
  quantity: 1,
}

const emptyOrderForm = {
  dealer: '',
  items: [{ ...emptyOrderItem }],
}

const emptyInventoryForm = {
  product_id: '',
  adjustment_quantity: '',
  updated_by: 'admin',
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })

  if (response.status === 204) {
    return null
  }

  const data = await response.json()
  if (!response.ok) {
    if (typeof data === 'string') {
      throw new Error(data)
    }

    if (data?.items?.length) {
      throw new Error(data.items.map((item) => item.message).join(' '))
    }

    if (data?.detail) {
      throw new Error(data.detail)
    }

    if (data && typeof data === 'object') {
      const fieldMessages = Object.entries(data)
        .map(([field, messages]) => {
          const text = Array.isArray(messages) ? messages.join(' ') : String(messages)
          return `${field}: ${text}`
        })
        .join(' ')

      if (fieldMessages) {
        throw new Error(fieldMessages)
      }
    }

    throw new Error(JSON.stringify(data))
  }
  return data
}

function App() {
  const [products, setProducts] = useState([])
  const [dealers, setDealers] = useState([])
  const [orders, setOrders] = useState([])
  const [inventory, setInventory] = useState([])
  const [summary, setSummary] = useState(null)
  const [productForm, setProductForm] = useState(emptyProductForm)
  const [dealerForm, setDealerForm] = useState(emptyDealerForm)
  const [orderForm, setOrderForm] = useState(emptyOrderForm)
  const [editingOrderId, setEditingOrderId] = useState(null)
  const [inventoryForm, setInventoryForm] = useState(emptyInventoryForm)
  const [activePanel, setActivePanel] = useState('dashboard')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const visibleOrders = orders.filter((order) => order.status !== 'draft')
  const statusSummary = orders.reduce(
    (totals, order) => {
      if (order.status === 'draft') {
        totals.draft += 1
      }
      if (order.status === 'confirmed') {
        totals.confirmed += 1
      }
      if (order.status === 'delivered') {
        totals.delivered += 1
      }
      return totals
    },
    { draft: 0, confirmed: 0, delivered: 0 },
  )
  const visibleDealerBreakdown = Object.values(
    visibleOrders.reduce((totals, order) => {
      const dealerId = String(order.dealer)
      if (!totals[dealerId]) {
        totals[dealerId] = {
          dealer_id: order.dealer,
          dealer_name: order.dealer_name,
          order_count: 0,
          total_amount: 0,
        }
      }

      totals[dealerId].order_count += 1
      totals[dealerId].total_amount += Number(order.total_amount || 0)
      return totals
    }, {}),
  )
    .map((dealer) => ({
      ...dealer,
      total_amount: dealer.total_amount.toFixed(2),
    }))
    .sort((left, right) => Number(right.total_amount) - Number(left.total_amount))

  const visibleProductBreakdown = Object.values(
    visibleOrders.reduce((totals, order) => {
      order.items.forEach((item) => {
        const productId = String(item.product_id)
        if (!totals[productId]) {
          totals[productId] = {
            product_id: item.product_id,
            product_name: item.product_name,
            sku: item.sku,
            total_quantity: 0,
            total_sales: 0,
          }
        }

        totals[productId].total_quantity += Number(item.quantity || 0)
        totals[productId].total_sales += Number(item.line_total || 0)
      })

      return totals
    }, {}),
  )
    .map((product) => ({
      ...product,
      total_sales: product.total_sales.toFixed(2),
    }))
    .sort((left, right) => Number(right.total_sales) - Number(left.total_sales))

  async function loadData() {
    try {
      setBusy(true)
      setError('')
      const [productData, dealerData, orderData, inventoryData, summaryData] = await Promise.all([
        request('/api/products/'),
        request('/api/dealers/'),
        request('/api/orders/'),
        request('/api/inventory/'),
        request('/api/orders/summary/'),
      ])

      setProducts(productData)
      setDealers(dealerData)
      setOrders(orderData)
      setInventory(inventoryData)
      setSummary(summaryData)
    } catch (loadError) {
      setError(loadError.message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  async function handleSubmit(action, successMessage) {
    try {
      setBusy(true)
      setError('')
      await action()
      await loadData()
    } catch (submitError) {
      setError(submitError.message)
    } finally {
      setBusy(false)
    }
  }

  function updateOrderItem(index, field, value) {
    setOrderForm((current) => {
      const items = current.items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item,
      )
      return { ...current, items }
    })
  }

  function addOrderItemRow() {
    setOrderForm((current) => ({
      ...current,
      items: [...current.items, { ...emptyOrderItem }],
    }))
  }

  function removeOrderItemRow(index) {
    setOrderForm((current) => {
      if (current.items.length === 1) {
        return current
      }
      return {
        ...current,
        items: current.items.filter((_, itemIndex) => itemIndex !== index),
      }
    })
  }

  function startEditingOrder(order) {
    setActivePanel('orders')
    setEditingOrderId(order.id)
    setOrderForm({
      dealer: String(order.dealer),
      items: order.items.map((item) => ({
        product_id: String(item.product_id),
        quantity: item.quantity,
      })),
    })
    setError('')
  }

  function cancelEditingOrder() {
    setEditingOrderId(null)
    setOrderForm(emptyOrderForm)
    setError('')
  }

  function formatDateTime(value) {
    if (!value) {
      return '-'
    }

    return new Date(value).toLocaleString('en-IN', {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="app-shell">
      <nav className="panel-tabs">
        {[
          ['dashboard', 'Dashboard'],
          ['products', 'Products'],
          ['dealers', 'Dealers'],
          ['orders', 'Orders'],
          ['inventory', 'Inventory'],
        ].map(([key, label]) => (
          <button
            key={key}
            className={activePanel === key ? 'tab active' : 'tab'}
            onClick={() => setActivePanel(key)}
            type="button"
          >
            {label}
          </button>
        ))}
      </nav>

      {error && (
        <section className="status-row">
          <div className="status error">{error}</div>
        </section>
      )}

      {activePanel === 'dashboard' && (
        <>
        <section className="dashboard-banner">
          <div className="dashboard-banner-copy">
            <span className="panel-kicker">Project Overview</span>
            <h2>Sales Order and Inventory workflow</h2>
            <p>
              Product setup, dealer onboarding, draft order handling, stock confirmation, and
              inventory corrections in one flow.
            </p>
          </div>
          <img
            className="dashboard-banner-image"
            src="/project-dashboard.svg"
            alt="Illustration showing the sales order and inventory management workflow"
          />
        </section>
        <section className="grid dashboard-grid">
          <article className="panel wide">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">Operational Summary</span>
                <h2>Order summary report</h2>
              </div>
            </div>
            <div className="summary-strip">
              <div>
                <span>Draft</span>
                <strong>{statusSummary.draft}</strong>
              </div>
              <div>
                <span>Confirmed</span>
                <strong>{statusSummary.confirmed}</strong>
              </div>
              <div>
                <span>Delivered</span>
                <strong>{statusSummary.delivered}</strong>
              </div>
            </div>
            <div className="split-layout">
              <div>
                <h3>Dealer Breakdown</h3>
                <div className="list-stack">
                  {visibleDealerBreakdown.map((dealer) => (
                    <div className="list-item" key={dealer.dealer_id}>
                      <div>
                        <strong>{dealer.dealer_name}</strong>
                        <span>{dealer.order_count} orders</span>
                      </div>
                      <em>{dealer.total_amount}</em>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3>Product Breakdown</h3>
                <div className="list-stack">
                  {visibleProductBreakdown.map((product) => (
                    <div className="list-item" key={product.product_id}>
                      <div>
                        <strong>{product.product_name}</strong>
                        <span>{product.sku}</span>
                      </div>
                      <em>
                        {product.total_quantity} units / {product.total_sales}
                      </em>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </article>

          <article className="panel">
            <span className="panel-kicker">Recent Orders</span>
            <h2>Workflow snapshot</h2>
            <div className="list-stack">
              {visibleOrders.slice(0, 5).map((order) => (
                <div className="list-item" key={order.id}>
                  <div>
                    <strong>{order.order_number}</strong>
                    <span>{order.dealer_name}</span>
                  </div>
                  <em className={`pill ${order.status}`}>{order.status}</em>
                </div>
              ))}
            </div>
          </article>
        </section>
        </>
      )}

      {activePanel === 'products' && (
        <section className="grid">
          <article className="panel">
            <span className="panel-kicker">Catalog Setup</span>
            <h2>Create product</h2>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault()
                const normalizedSku = productForm.sku.trim().toUpperCase()
                const duplicateProduct = products.find(
                  (product) => product.sku.toUpperCase() === normalizedSku,
                )

                if (duplicateProduct) {
                  setError(`Already exists (SKU: ${duplicateProduct.sku})`)
                  return
                }

                handleSubmit(
                  () =>
                    request('/api/products/', {
                      method: 'POST',
                      body: JSON.stringify({ ...productForm, sku: normalizedSku }),
                    }),
                  'Product created successfully.',
                )
                setProductForm(emptyProductForm)
              }}
            >
              <label>
                SKU
                <input
                  value={productForm.sku}
                  onChange={(event) => setProductForm({ ...productForm, sku: event.target.value })}
                  required
                />
              </label>
              <label>
                Name
                <input
                  value={productForm.name}
                  onChange={(event) =>
                    setProductForm({ ...productForm, name: event.target.value })
                  }
                  required
                />
              </label>
              <label className="full">
                Description
                <textarea
                  value={productForm.description}
                  onChange={(event) =>
                    setProductForm({ ...productForm, description: event.target.value })
                  }
                />
              </label>
              <label>
                Unit Price
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={productForm.unit_price}
                  onChange={(event) =>
                    setProductForm({ ...productForm, unit_price: event.target.value })
                  }
                  required
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={productForm.is_active}
                  onChange={(event) =>
                    setProductForm({ ...productForm, is_active: event.target.checked })
                  }
                />
                Active
              </label>
              <button className="primary-button" disabled={busy} type="submit">
                Save Product
              </button>
            </form>
          </article>

          <article className="panel wide">
            <span className="panel-kicker">Catalog View</span>
            <h2>Products and live stock</h2>
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Name</th>
                  <th>Price</th>
                  <th>Stock</th>
                </tr>
              </thead>
              <tbody>
                {products.map((product) => (
                  <tr key={product.id}>
                    <td>{product.sku}</td>
                    <td>{product.name}</td>
                    <td>{product.unit_price}</td>
                    <td>{product.stock_quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        </section>
      )}

      {activePanel === 'dealers' && (
        <section className="grid">
          <article className="panel">
            <span className="panel-kicker">Dealer Setup</span>
            <h2>Create dealer</h2>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault()
                handleSubmit(
                  () =>
                    request('/api/dealers/', {
                      method: 'POST',
                      body: JSON.stringify(dealerForm),
                    }),
                  'Dealer created successfully.',
                )
                setDealerForm(emptyDealerForm)
              }}
            >
              <label>
                Code
                <input
                  value={dealerForm.code}
                  onChange={(event) => setDealerForm({ ...dealerForm, code: event.target.value })}
                  required
                />
              </label>
              <label>
                Name
                <input
                  value={dealerForm.name}
                  onChange={(event) => setDealerForm({ ...dealerForm, name: event.target.value })}
                  required
                />
              </label>
              <label>
                Email
                <input
                  type="email"
                  pattern="[a-z0-9._%+-]+@gmail\.com"
                  placeholder="name@gmail.com"
                  value={dealerForm.email}
                  onChange={(event) =>
                    setDealerForm({ ...dealerForm, email: event.target.value.toLowerCase() })
                  }
                  required
                />
              </label>
              <label>
                Phone
                <input
                  type="tel"
                  inputMode="numeric"
                  maxLength="10"
                  pattern="[0-9]{10}"
                  value={dealerForm.phone}
                  onChange={(event) =>
                    setDealerForm({
                      ...dealerForm,
                      phone: event.target.value.replace(/\D/g, '').slice(0, 10),
                    })
                  }
                  required
                />
              </label>
              <label className="full">
                Address
                <textarea
                  value={dealerForm.address}
                  onChange={(event) =>
                    setDealerForm({ ...dealerForm, address: event.target.value })
                  }
                />
              </label>
              <button className="primary-button" disabled={busy} type="submit">
                Save Dealer
              </button>
            </form>
          </article>

          <article className="panel wide">
            <span className="panel-kicker">Partner Network</span>
            <h2>Dealers</h2>
            <table>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Phone</th>
                </tr>
              </thead>
              <tbody>
                {dealers.map((dealer) => (
                  <tr key={dealer.id}>
                    <td>{dealer.code}</td>
                    <td>{dealer.name}</td>
                    <td>{dealer.email}</td>
                    <td>{dealer.phone}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        </section>
      )}

      {activePanel === 'orders' && (
        <section className="grid">
          <article className="panel">
            <span className="panel-kicker">Order Desk</span>
            <h2>{editingOrderId ? 'Edit draft order' : 'Create draft order'}</h2>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault()
                const payload = {
                  dealer: Number(orderForm.dealer),
                  items: orderForm.items.map((item) => ({
                    product_id: Number(item.product_id),
                    quantity: Number(item.quantity),
                  })),
                }
                handleSubmit(
                  () =>
                    request(editingOrderId ? `/api/orders/${editingOrderId}/` : '/api/orders/', {
                      method: editingOrderId ? 'PUT' : 'POST',
                      body: JSON.stringify(payload),
                    }),
                  editingOrderId ? 'Draft order updated successfully.' : 'Draft order created successfully.',
                )
                setEditingOrderId(null)
                setOrderForm(emptyOrderForm)
              }}
            >
              <label className="full">
                Dealer
                <select
                  value={orderForm.dealer}
                  onChange={(event) => setOrderForm({ ...orderForm, dealer: event.target.value })}
                  required
                >
                  <option value="">Select dealer</option>
                  {dealers.map((dealer) => (
                    <option key={dealer.id} value={dealer.id}>
                      {dealer.name}
                    </option>
                  ))}
                </select>
              </label>

              <div className="full item-group">
                {orderForm.items.map((item, index) => (
                  <div className="item-row" key={`${index}-${item.product_id}`}>
                    <select
                      value={item.product_id}
                      onChange={(event) => updateOrderItem(index, 'product_id', event.target.value)}
                      required
                    >
                      <option value="">Select product</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name} ({product.sku})
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min="1"
                      value={item.quantity}
                      onChange={(event) => updateOrderItem(index, 'quantity', event.target.value)}
                      required
                    />
                    <button type="button" className="ghost-button" onClick={() => removeOrderItemRow(index)}>
                      Remove
                    </button>
                  </div>
                ))}
                <button className="secondary-button" onClick={addOrderItemRow} type="button">
                  Add Item
                </button>
              </div>

              <div className="action-row full">
                <button className="primary-button" disabled={busy} type="submit">
                  {editingOrderId ? 'Update Draft Order' : 'Save Draft Order'}
                </button>
                {editingOrderId && (
                  <button className="ghost-button" onClick={cancelEditingOrder} type="button">
                    Cancel
                  </button>
                )}
              </div>
            </form>
          </article>

          <article className="panel wide">
            <span className="panel-kicker">Order Workflow</span>
            <h2>Orders</h2>
            <div className="order-stack">
              {orders.map((order) => (
                <div className="order-card" key={order.id}>
                  <div className="order-head">
                    <div>
                      <strong>{order.order_number}</strong>
                      <span>{order.dealer_name}</span>
                    </div>
                    <span className={`pill ${order.status}`}>{order.status}</span>
                  </div>
                  <div className="mini-grid">
                    <span>Total: {order.total_amount}</span>
                    <span>Items: {order.items.length}</span>
                  </div>
                  <ul className="order-items">
                    {order.items.map((item) => (
                      <li key={item.id}>
                        {item.product_name} x {item.quantity} = {item.line_total}
                      </li>
                    ))}
                  </ul>
                  <div className="action-row">
                    <button
                      className="ghost-button"
                      disabled={busy || order.status !== 'draft'}
                      onClick={() => startEditingOrder(order)}
                      type="button"
                    >
                      Edit
                    </button>
                    <button
                      className="secondary-button"
                      disabled={busy || order.status !== 'draft'}
                      onClick={() =>
                        handleSubmit(
                          () => request(`/api/orders/${order.id}/confirm/`, { method: 'POST' }),
                          `Order ${order.order_number} confirmed.`,
                        )
                      }
                      type="button"
                    >
                      Confirm
                    </button>
                    <button
                      className="ghost-button"
                      disabled={busy || order.status === 'delivered'}
                      onClick={() =>
                        handleSubmit(
                          () => request(`/api/orders/${order.id}/`, { method: 'DELETE' }),
                          `Order ${order.order_number} deleted.`,
                        )
                      }
                      type="button"
                    >
                      Delete
                    </button>
                    <button
                      className="primary-button"
                      disabled={busy || order.status !== 'confirmed'}
                      onClick={() =>
                        handleSubmit(
                          () => request(`/api/orders/${order.id}/deliver/`, { method: 'POST' }),
                          `Order ${order.order_number} delivered.`,
                        )
                      }
                      type="button"
                    >
                      Deliver
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </article>
        </section>
      )}

      {activePanel === 'inventory' && (
        <section className="grid">
          <article className="panel">
            <span className="panel-kicker">Stock Control</span>
            <h2>Adjust inventory</h2>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault()
                handleSubmit(
                  () =>
                    request(`/api/inventory/${inventoryForm.product_id}/`, {
                        method: 'PUT',
                        body: JSON.stringify({
                        adjustment_quantity: Number(inventoryForm.adjustment_quantity),
                        updated_by: inventoryForm.updated_by,
                      }),
                    }),
                  'Inventory adjusted successfully.',
                )
                setInventoryForm(emptyInventoryForm)
              }}
            >
              <label className="full">
                Product
                <select
                  value={inventoryForm.product_id}
                  onChange={(event) =>
                    setInventoryForm({ ...inventoryForm, product_id: event.target.value })
                  }
                  required
                >
                  <option value="">Select product</option>
                  {products.map((product) => (
                    <option key={product.id} value={product.id}>
                      {product.name} ({product.sku})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Adjustment Quantity
                <input
                  type="number"
                  value={inventoryForm.adjustment_quantity}
                  onChange={(event) =>
                    setInventoryForm({
                      ...inventoryForm,
                      adjustment_quantity: event.target.value,
                    })
                  }
                  required
                />
              </label>
              <label>
                Updated By
                <input
                  value={inventoryForm.updated_by}
                  onChange={(event) =>
                    setInventoryForm({ ...inventoryForm, updated_by: event.target.value })
                  }
                  placeholder="Optional"
                />
              </label>
              <button className="primary-button" disabled={busy} type="submit">
                Apply Adjustment
              </button>
            </form>
          </article>

          <article className="panel wide">
            <span className="panel-kicker">Live Inventory</span>
            <h2>Current stock positions</h2>
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Product</th>
                  <th>Quantity</th>
                  <th>Updated By</th>
                  <th>Updated At</th>
                </tr>
              </thead>
              <tbody>
                {inventory.map((item) => (
                  <tr key={item.product_id}>
                    <td>{item.sku}</td>
                    <td>{item.product_name}</td>
                    <td>{item.available_quantity}</td>
                    <td>{item.last_updated_by || 'system'}</td>
                    <td>{formatDateTime(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        </section>
      )}
    </div>
  )
}

export default App
