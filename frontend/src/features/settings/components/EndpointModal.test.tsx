/**
 * 「设置接口」弹窗：地址必须能点得通，所以只接受 http(s) 绝对地址；
 * 模型名可留空（沿用原值），不逼着用户去查。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EndpointModal } from './EndpointModal';
import type { ModelOut } from '../api';

const workbuddy: ModelOut = {
  id: 'env:workbuddy',
  provider: 'workbuddy',
  base_url: '',
  model: 'workbuddy-chat',
  api_key_ref: 'env:WORKBUDDY_API_KEY',
  configured: false,
  enabled: true,
  priority: 0,
  builtin: true,
  last_probe: null,
  extra: {},
};

function renderModal(model: ModelOut = workbuddy) {
  const onSave = vi.fn();
  const onClose = vi.fn();
  render(
    <EndpointModal model={model} saving={false} error={null} onClose={onClose} onSave={onSave} />,
  );
  return { onSave, onClose };
}

describe('EndpointModal', () => {
  it('标题用可读名，并说明不用自己拼 /chat/completions', () => {
    renderModal();
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByText('设置 WorkBuddy 的接口')).toBeTruthy();
    expect(screen.getByText(/不用/)).toBeTruthy();
  });

  it('不填地址时保存按钮不可点', () => {
    renderModal();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
  });

  it('填了非 http(s) 地址会被拦下', () => {
    renderModal();
    fireEvent.change(screen.getByLabelText('接口地址'), {
      target: { value: 'api.example.com/v1' },
    });
    fireEvent.blur(screen.getByLabelText('接口地址'));
    expect(screen.getByText(/要以 http:\/\/ 或 https:\/\//)).toBeTruthy();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
  });

  it('合法地址去掉结尾斜杠后保存，模型名可改', () => {
    const { onSave } = renderModal();
    fireEvent.change(screen.getByLabelText('接口地址'), {
      target: { value: 'https://api.example.com/v1/' },
    });
    fireEvent.change(screen.getByLabelText('模型名'), { target: { value: 'wb-large' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(onSave).toHaveBeenCalledWith('https://api.example.com/v1', 'wb-large');
  });

  it('已填过的地址进来就带出来，改完点取消不会保存', () => {
    const { onSave, onClose } = renderModal({ ...workbuddy, base_url: 'https://old.test/v1' });
    expect((screen.getByLabelText('接口地址') as HTMLInputElement).value).toBe(
      'https://old.test/v1',
    );
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});
