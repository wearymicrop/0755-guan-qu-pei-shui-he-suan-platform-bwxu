const confirmBox = document.querySelector('#confirm-box');
if (confirmBox) {
  const outletSelect = document.querySelector('#confirm-outlet');
  const statusLine = document.querySelector('#confirm-status');
  const list = document.querySelector('#confirm-list');
  const button = document.querySelector('#confirm-btn');

  function refresh(runId) {
    return fetch(`/api/runs/${runId}/confirmations`).then(response => response.json()).then(data => {
      list.replaceChildren(...data.confirmed.map(row => {
        const item = document.createElement('li');
        item.textContent = `${row.outlet} 已确认 ${row.amount_l} L`;
        return item;
      }));
    });
  }

  button.addEventListener('click', async () => {
    if (!activeRun) {
      statusLine.textContent = '请先在右上角核算归档，再确认实配。';
      return;
    }
    const option = outletSelect.selectedOptions[0];
    button.disabled = true;
    statusLine.textContent = '正在确认…';
    try {
      const response = await fetch(`/api/runs/${activeRun}/confirmations`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({outlet: option.value, amount_l: Number(option.dataset.amount)}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message);
      statusLine.textContent = data.created ? '已确认并落账' : '该斗口已确认，未重复累加';
      await refresh(activeRun);
    } catch (error) {
      statusLine.textContent = error.message || '确认失败。';
    } finally {
      button.disabled = false;
    }
  });
}
